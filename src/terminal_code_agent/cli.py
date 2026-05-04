import argparse
import json
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from terminal_code_agent.config import load_settings
from terminal_code_agent.graph import build_graph
from terminal_code_agent.logging_utils import JsonlLogger
from terminal_code_agent.schemas import ApprovalResume, PendingToolCall

console = Console()
readline: Any | None

try:
    import readline as _readline
except ImportError:  # pragma: no cover - readline is platform-dependent.
    readline = None
else:
    readline = _readline


def configure_line_editor() -> None:
    """Enable stable terminal line editing for input prompts."""

    if readline is None:
        return
    readline.parse_and_bind("set editing-mode emacs")
    readline.parse_and_bind("set bind-tty-special-chars on")
    readline.parse_and_bind('"\\C-h": backward-delete-char')
    readline.parse_and_bind('"\\e[3~": delete-char')


def read_cli_input(prompt: str) -> str:
    return input(prompt)


def resolve_workdir(path: str) -> Path:
    workdir = Path(path).expanduser().resolve()
    if not workdir.exists() or not workdir.is_dir():
        raise SystemExit(f"工作目录不存在或不是目录: {path}")
    return workdir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="terminal-code-agent")
    parser.add_argument("--workdir", required=True, help="agent 工作目录")
    parser.add_argument("--thread-id", default="default", help="会话 ID，用于 checkpointer")
    parser.add_argument("--env-file", default=".env", help="配置文件路径")
    parser.add_argument("--log-level", default=None, help="覆盖配置中的日志级别")
    parser.add_argument("--no-color", action="store_true", help="禁用彩色终端输出")
    return parser.parse_args()


def _summarize_call(call: dict[str, Any]) -> str:
    args = call.get("args", {})
    compact = json.dumps(args, ensure_ascii=False)
    if len(compact) > 500:
        compact = compact[:500] + "...[TRUNCATED]"
    return compact


def print_header(workdir: Path, thread_id: str, log_path: Path) -> None:
    table = Table.grid(padding=(0, 1))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    table.add_row("workdir", str(workdir))
    table.add_row("thread", thread_id)
    table.add_row("log", str(log_path))
    console.print(Panel(table, title="terminal-code-agent", border_style="cyan"))


def print_approval_request(payload: dict[str, Any]) -> None:
    table = Table(show_header=True, header_style="bold cyan", expand=True)
    table.add_column("tool", no_wrap=True)
    table.add_column("arguments")
    for call in payload.get("tool_calls", []):
        table.add_row(str(call.get("name", "")), _summarize_call(call))
    question = payload.get("question", "是否允许执行工具调用？")
    risk = payload.get("risk", "")
    console.print(
        Panel(
            table,
            title=str(question),
            subtitle=f"risk: {risk}",
            border_style="yellow",
        )
    )


def ask_user_for_approval(payload: dict[str, Any]) -> dict[str, Any]:
    """CLI 审批入口；只处理 y/n/edit，不在 graph 节点中读取 stdin。"""

    print_approval_request(payload)

    while True:
        answer = read_cli_input("approve [y/n/edit] > ").strip().lower()
        if answer in {"y", "yes"}:
            return ApprovalResume(decision="approved").model_dump()
        if answer in {"n", "no"}:
            return ApprovalResume(decision="rejected").model_dump()
        if answer in {"e", "edit"}:
            raw = read_cli_input("edited_tool_calls JSON > ").strip()
            try:
                edited = [PendingToolCall.model_validate(item) for item in json.loads(raw)]
            except Exception as exc:
                console.print(f"[red]编辑内容无效:[/red] {exc}")
                continue
            return ApprovalResume(decision="approved", edited_tool_calls=edited).model_dump()
        console.print("[yellow]请输入 y、n 或 edit。[/yellow]")


def _extract_interrupt(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict) or "__interrupt__" not in result:
        return None
    interrupt_item = result["__interrupt__"][0]
    return getattr(interrupt_item, "value", interrupt_item)


def run_graph_with_approval_loop(
    graph: Any, state_input: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    result = graph.invoke(state_input, config=config)
    while payload := _extract_interrupt(result):
        resume_payload = ask_user_for_approval(payload)
        result = graph.invoke(Command(resume=resume_payload), config=config)
    return result


def print_final(result: dict[str, Any]) -> None:
    answer = str(result.get("final_answer", ""))
    console.print(Panel(Text(answer), title="answer", border_style="green"))


def main() -> None:
    configure_line_editor()
    args = parse_args()
    global console
    console = Console(no_color=args.no_color)
    settings = load_settings(args.env_file)
    if args.log_level:
        settings.log_level = args.log_level
    workdir = resolve_workdir(args.workdir)
    logger = JsonlLogger(settings.log_dir, level=settings.log_level)
    graph = build_graph(InMemorySaver(), settings=settings, logger=logger)
    config = {"configurable": {"thread_id": args.thread_id}}
    print_header(workdir, args.thread_id, logger.path)

    while True:
        try:
            user_input = read_cli_input("user > ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            break
        state_input = {
            "thread_id": args.thread_id,
            "workdir": str(workdir),
            "user_input": user_input,
        }
        result = run_graph_with_approval_loop(graph, state_input, config)
        print_final(result)
