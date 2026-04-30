from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from typing import cast

from mcp import ClientSession
from mcp.client.sse import sse_client


DEFAULT_URL = "http://127.0.0.1:8000/sse"

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject = dict[str, JsonValue]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="code-agent-mcp-client",
        description="Connect to the standalone Code Agent MCP example server over legacy SSE.",
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="MCP SSE endpoint URL.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list-tools", help="List tools exposed by the server.")

    call_parser = subparsers.add_parser("call", help="Call a tool exposed by the server.")
    call_parser.add_argument("tool_name", help="Tool name, for example code_agent_add.")
    call_parser.add_argument(
        "--arguments",
        default="{}",
        help='JSON object to pass as tool arguments, for example \'{"a":2,"b":3}\'.',
    )

    return parser.parse_args(argv)


def parse_arguments_json(raw_arguments: str) -> JsonObject:
    try:
        parsed = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ValueError(f"arguments must be a JSON object: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("arguments must be a JSON object")
    if not all(isinstance(key, str) for key in parsed):
        raise ValueError("argument names must be strings")

    return cast(JsonObject, parsed)


async def list_tools(url: str) -> list[dict[str, object]]:
    async with sse_client(url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools_result = await session.list_tools()

    tools: list[dict[str, object]] = []
    for tool in tools_result.tools:
        tools.append(
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.inputSchema,
            }
        )
    return tools


async def call_tool(url: str, tool_name: str, arguments: JsonObject) -> dict[str, object]:
    async with sse_client(url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=arguments)

    content: list[object] = []
    for item in result.content:
        if hasattr(item, "model_dump"):
            content.append(item.model_dump(mode="json"))
        else:
            content.append(str(item))

    return {
        "isError": result.isError,
        "structuredContent": result.structuredContent,
        "content": content,
    }


async def run(args: argparse.Namespace) -> object:
    if args.command == "list-tools":
        return await list_tools(args.url)
    if args.command == "call":
        return await call_tool(args.url, args.tool_name, parse_arguments_json(args.arguments))
    raise ValueError(f"unknown command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = asyncio.run(run(parse_args(argv)))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        return 130

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
