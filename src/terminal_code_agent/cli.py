import json
import uuid
from pathlib import Path
from typing import Annotated, Any

import typer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from terminal_code_agent.config import load_settings
from terminal_code_agent.graph import build_graph, configure_event_console
from terminal_code_agent.logging_utils import JsonlLogger
from terminal_code_agent.schemas import ApprovalResume, PendingToolCall

app = typer.Typer(add_completion=False)
console = Console()
readline: Any | None
CODE_FIELD_PLACEHOLDER = "<见下方代码块>"
LANGUAGE_BY_SUFFIX = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".json": "json",
    ".md": "markdown",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".html": "html",
    ".css": "css",
    ".sh": "bash",
    ".bash": "bash",
    ".sql": "sql",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
    ".java": "java",
    ".rs": "rust",
    ".go": "go",
}

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
        raise typer.BadParameter(f"工作目录不存在或不是目录: {path}")
    return workdir


def generate_thread_id() -> str:
    return str(uuid.uuid4())


def build_graph_config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def parse_resume_command(user_input: str) -> str | None:
    parts = user_input.split()
    if not parts or parts[0] != "/resume":
        return None
    if len(parts) != 2:
        raise ValueError("用法: /resume <thread-id>")
    return parts[1]


def has_checkpoint(graph: Any, thread_id: str) -> bool:
    snapshot = graph.get_state(build_graph_config(thread_id))
    return bool(getattr(snapshot, "values", None))


def _language_for_path(path: Any) -> str:
    if not isinstance(path, str):
        return ""
    return LANGUAGE_BY_SUFFIX.get(Path(path).suffix.lower(), "")


def _fenced_code_block(content: str, language: str = "") -> str:
    fence = "```"
    while fence in content:
        fence += "`"
    body = content if content.endswith("\n") else f"{content}\n"
    return f"{fence}{language}\n{body}{fence}"


def _format_call_arguments_markdown(call: dict[str, Any]) -> str:
    raw_args = call.get("args", {})
    args = dict(raw_args) if isinstance(raw_args, dict) else {"value": raw_args}
    code_blocks: list[str] = []
    tool_name = str(call.get("name", ""))

    if tool_name == "write_file" and isinstance(args.get("content"), str):
        content = str(args["content"])
        args["content"] = CODE_FIELD_PLACEHOLDER
        language = _language_for_path(args.get("path"))
        code_blocks.append(_fenced_code_block(content, language))
    elif tool_name == "apply_patch" and isinstance(args.get("patch"), str):
        patch = str(args["patch"])
        args["patch"] = CODE_FIELD_PLACEHOLDER
        code_blocks.append(_fenced_code_block(patch, "diff"))

    formatted = json.dumps(args, ensure_ascii=False, indent=2, default=str)
    sections = [f"```json\n{formatted}\n```", *code_blocks]
    return "\n\n".join(sections)


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
        table.add_row(str(call.get("name", "")), Markdown(_format_call_arguments_markdown(call)))
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
    console.print(Panel(Markdown(answer), title="answer", border_style="green"))


@app.command()
def run(
    workdir: Annotated[str, typer.Option("--workdir", help="agent 工作目录")],
    thread_id: Annotated[
        str | None,
        typer.Option("--thread-id", help="会话 ID；未指定时自动生成新的 thread-id"),
    ] = None,
    env_file: Annotated[str, typer.Option("--env-file", help="配置文件路径")] = ".env",
    log_level: Annotated[
        str | None, typer.Option("--log-level", help="覆盖配置中的日志级别")
    ] = None,
    no_color: Annotated[bool, typer.Option("--no-color", help="禁用彩色终端输出")] = False,
) -> None:
    configure_line_editor()
    global console
    console = Console(no_color=no_color)
    configure_event_console(no_color=no_color)
    settings = load_settings(env_file)
    if log_level:
        settings.log_level = log_level
    resolved_workdir = resolve_workdir(workdir)
    logger = JsonlLogger(settings.log_dir, level=settings.log_level)
    current_thread_id = thread_id or generate_thread_id()
    settings.checkpoint_db.parent.mkdir(parents=True, exist_ok=True)

    with SqliteSaver.from_conn_string(str(settings.checkpoint_db)) as checkpointer:
        graph = build_graph(checkpointer, settings=settings, logger=logger)
        print_header(resolved_workdir, current_thread_id, logger.path)

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
            try:
                resume_thread_id = parse_resume_command(user_input)
            except ValueError as exc:
                console.print(f"[yellow]{exc}[/yellow]")
                continue
            if resume_thread_id is not None:
                if not has_checkpoint(graph, resume_thread_id):
                    console.print(f"[red]未找到 thread-id:[/red] {resume_thread_id}")
                    continue
                current_thread_id = resume_thread_id
                console.print(f"[cyan]已恢复 thread-id:[/cyan] {current_thread_id}")
                continue
            config = build_graph_config(current_thread_id)
            state_input = {
                "thread_id": current_thread_id,
                "workdir": str(resolved_workdir),
                "user_input": user_input,
            }
            result = run_graph_with_approval_loop(graph, state_input, config)
            print_final(result)


def main() -> None:
    app()
