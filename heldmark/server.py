"""The heldmark-records MCP server.

Exactly three tools: append_event, list_events, update_profile.
One resource: learner://{id}/events.
A call to any other tool is rejected and logged.

Run it over stdio with:  python -m heldmark.server
"""

import json
import re

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from . import __version__, store
from .records import DEFAULT_TEACHER, Records, Rejected

NAME = "heldmark-records"
EVENTS_URI = re.compile(r"^learner://([^/]+)/events$")

_LEARNER = {"learner_id": {"type": "string", "description": "The one learner this call is about."}}

TOOL_LIST = [
    types.Tool(
        name="append_event",
        description="Store one cited quiz, project, or note for one learner. An event with no source is refused.",
        input_schema={
            "type": "object",
            "properties": {
                **_LEARNER,
                "kind": {"type": "string", "description": "Task kind, e.g. word_problem, calculation, note."},
                "source": {"type": "string", "description": "The quiz, project, or note this came from."},
                "score": {"type": "number"},
                "text": {"type": "string", "description": "The wording of a teacher note."},
                "school": {"type": "string"},
                "date": {"type": "string", "description": "ISO date of the event, e.g. 2026-03-12."},
            },
            "required": ["learner_id", "kind", "source"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="list_events",
        description="Return one learner's events in order. It cannot see classmates.",
        input_schema={
            "type": "object",
            "properties": _LEARNER,
            "required": ["learner_id"],
            "additionalProperties": False,
        },
    ),
    types.Tool(
        name="update_profile",
        description="Rewrite the sourced profile from the rules in code, and nothing else.",
        input_schema={
            "type": "object",
            "properties": {
                **_LEARNER,
                "shown_to": {"type": "string", "description": "The named teacher the profile is shown to."},
            },
            "required": ["learner_id"],
            "additionalProperties": False,
        },
    ),
]


def _result(payload, is_error: bool = False) -> types.CallToolResult:
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=is_error)


def build_server(records: Records) -> Server:
    async def on_list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=TOOL_LIST)

    async def on_call_tool(ctx, params) -> types.CallToolResult:
        args = dict(params.arguments or {})
        try:
            if params.name == "append_event":
                return _result(records.append_event(**args))
            if params.name == "list_events":
                return _result(records.list_events(**args))
            if params.name == "update_profile":
                args.setdefault("shown_to", DEFAULT_TEACHER)
                return _result(records.update_profile(**args)["text"])
            records.refuse(params.name, args)
        except Rejected as refusal:
            return _result(str(refusal), is_error=True)
        except TypeError as error:
            return _result(f"Bad arguments for {params.name}: {error}", is_error=True)

    async def on_list_resource_templates(ctx, params) -> types.ListResourceTemplatesResult:
        return types.ListResourceTemplatesResult(
            resource_templates=[
                types.ResourceTemplate(
                    name="learner-events",
                    uri_template="learner://{id}/events",
                    description="One learner's cited events, oldest first.",
                    mime_type="application/json",
                )
            ]
        )

    async def on_read_resource(ctx, params) -> types.ReadResourceResult:
        match = EVENTS_URI.match(str(params.uri))
        if not match:
            raise ValueError(f"Unknown resource: {params.uri}. The only resource is learner://{{id}}/events.")
        events = records.list_events(match.group(1))
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=str(params.uri), mime_type="application/json", text=json.dumps(events, indent=2)
                )
            ]
        )

    return Server(
        NAME,
        version=__version__,
        instructions="Stores one learner's cited events and rewrites their sourced profile. "
        "There is no tool to label, rank, score, share, or recommend.",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
        on_list_resource_templates=on_list_resource_templates,
        on_read_resource=on_read_resource,
    )


async def serve() -> None:
    server = build_server(Records(store.connect()))
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    anyio.run(serve)


if __name__ == "__main__":
    main()
