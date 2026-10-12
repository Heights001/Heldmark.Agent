"""The only way the graph reaches a tool.

Two MCP servers sit behind it:

- heldmark-records, ours. It stores and changes learner facts and logs its own calls.
- the official Filesystem server, borrowed. It is scoped to one intake folder
  and used for reading only. Its write tools are never called.

The Filesystem server knows nothing about our audit log, so each read is
appended to the log here, with input, output, timestamp, and learner id.
This module writes audit rows only. It never touches events or profiles.
"""

import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

from . import store

FILESYSTEM_READS = ("list_directory", "read_text_file")
FILESYSTEM_JS = (
    Path(__file__).resolve().parent.parent
    / "node_modules" / "@modelcontextprotocol" / "server-filesystem" / "dist" / "index.js"
)


class ToolRefused(Exception):
    pass


def records_server(db: str) -> StdioServerParameters:
    """Our server as a child process, pointed at one SQLite file."""
    return StdioServerParameters(
        command=sys.executable, args=["-m", "heldmark.server"], env={**os.environ, "HELDMARK_DB": db}
    )


def filesystem_server(intake_dir: str):
    """The borrowed server as a child process, allowed to see one directory and nothing else."""
    if not FILESYSTEM_JS.exists():
        raise FileNotFoundError("The Filesystem MCP server is not installed. Run: npm install")
    params = StdioServerParameters(command="node", args=[str(FILESYSTEM_JS), os.path.realpath(intake_dir)])
    return stdio_client(params, errlog=open(os.devnull, "w"))


class Toolbox:
    def __init__(self, records, filesystem, db: str, learner_id: str):
        """records and filesystem are anything mcp.Client accepts: a child process, or a server object in tests."""
        self._servers = {"records": records, "filesystem": filesystem}
        self._clients: dict[str, Client] = {}
        self._stack = AsyncExitStack()
        self._audit = store.connect(db)
        self.learner_id = learner_id
        self.calls = 0

    async def __aenter__(self):
        for name, server in self._servers.items():
            self._clients[name] = await self._stack.enter_async_context(Client(server))
        return self

    async def __aexit__(self, *exc):
        await self._stack.aclose()
        self._audit.close()

    async def records(self, tool: str, **arguments):
        """Call heldmark-records. The server logs the call itself, including a refusal."""
        self.calls += 1
        return await self._clients["records"].call_tool(tool, arguments)

    async def filesystem(self, tool: str, **arguments) -> str:
        """Read through the borrowed server. Anything that is not a read is refused and logged."""
        self.calls += 1
        name = f"filesystem.{tool}"
        if tool not in FILESYSTEM_READS:
            reason = f"Rejected: the Filesystem server is used for reading only, not '{tool}'."
            store.log(self._audit, name, self.learner_id, arguments, {"rejected": reason}, "rejected")
            raise ToolRefused(reason)
        result = await self._clients["filesystem"].call_tool(tool, arguments)
        text = "\n".join(block.text for block in result.content if getattr(block, "text", None))
        if result.is_error:
            store.log(self._audit, name, self.learner_id, arguments, {"rejected": text}, "rejected")
            raise ToolRefused(text)
        store.log(self._audit, name, self.learner_id, arguments, {"text": text})
        return text
