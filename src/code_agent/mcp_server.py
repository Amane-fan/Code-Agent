from __future__ import annotations

import argparse

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

code_agent_mcp = FastMCP(
    "code_agent_mcp",
    host=DEFAULT_HOST,
    port=DEFAULT_PORT,
)


@code_agent_mcp.tool(
    name="code_agent_echo",
    annotations=ToolAnnotations(
        title="Echo Message",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def code_agent_echo(message: str) -> dict[str, object]:
    """返回输入消息及其字符数。"""

    return {"message": message, "characters": len(message)}


@code_agent_mcp.tool(
    name="code_agent_add",
    annotations=ToolAnnotations(
        title="Add Numbers",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def code_agent_add(a: int, b: int) -> dict[str, object]:
    """将两个整数相加并返回结构化结果。"""

    return {"a": a, "b": b, "result": a + b}


@code_agent_mcp.tool(
    name="code_agent_word_count",
    annotations=ToolAnnotations(
        title="Count Words",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
def code_agent_word_count(text: str) -> dict[str, object]:
    """统计文本中的字符数、行数和空白分隔的单词数。"""

    return {
        "characters": len(text),
        "lines": len(text.splitlines()) if text else 0,
        "words": len(text.split()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="code-agent-mcp-server",
        description="通过 legacy SSE 运行独立的 Code Agent MCP 示例服务。",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="绑定的主机地址。")
    parser.add_argument("--port", default=DEFAULT_PORT, type=int, help="绑定的端口号。")
    args = parser.parse_args(argv)

    code_agent_mcp.settings.host = args.host
    code_agent_mcp.settings.port = args.port
    code_agent_mcp.run(transport="sse")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
