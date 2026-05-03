from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import click
import typer
from rich.console import Console, RenderableType
from rich.json import JSON
from rich.panel import Panel
from rich.text import Text
from typer.main import get_command

from code_agent.agent import CodingAgent
from code_agent.config import DEFAULT_PROVIDER, AgentConfig
from code_agent.models import AgentEvent, ModelCallUsage
from code_agent.terminal import read_prompt


EXIT_COMMANDS = {"/exit", "/quit"}
COMPACT_COMMAND = "/compact"
CLEAR_COMMAND = "/clear"
MEMORY_COMMAND = "/memory"
SLASH_COMMANDS = sorted([*EXIT_COMMANDS, COMPACT_COMMAND, CLEAR_COMMAND, MEMORY_COMMAND])

app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="针对单一 workspace 的交互式 AI 编程 Agent。",
)


class TerminalRenderer:
    """用 Rich 渲染 Agent 事件和 CLI 状态消息。"""

    def __init__(self, console: Console) -> None:
        self.console = console

    def event(self, event: AgentEvent) -> None:
        title = {
            "memory": "Memory",
            "task": "Task",
            "summary": "Summary",
            "tool_call": "Tool Call",
            "tool_result": "Tool Result",
            "final_answer": "Final Answer",
        }[event.type]
        border_style = {
            "memory": "cyan",
            "task": "blue",
            "summary": "green",
            "tool_call": "yellow",
            "tool_result": "magenta",
            "final_answer": "bold green",
        }[event.type]
        renderable: RenderableType
        if event.type in {"tool_call", "tool_result"}:
            renderable = self._json_or_text(event.content)
        else:
            renderable = Text(event.content)
        self.console.print(Panel(renderable, title=title, border_style=border_style))

    def model_usage(self, model_call: ModelCallUsage) -> None:
        usage = model_call.usage
        if usage is None:
            message = (
                f"provider: {model_call.provider}\n"
                f"model: {model_call.model}\n"
                f"purpose: {model_call.purpose}\n"
                "tokens: unknown"
            )
        else:
            message = (
                f"provider: {model_call.provider}\n"
                f"model: {model_call.model}\n"
                f"purpose: {model_call.purpose}\n"
                f"prompt: {_format_token_count(usage.prompt_tokens)}\n"
                f"completion: {_format_token_count(usage.completion_tokens)}\n"
                f"total: {_format_token_count(usage.total_tokens)}"
            )
        self.console.print(Panel(Text(message), title="Token Usage", border_style="cyan"))

    def info(self, message: str, *, title: str = "Info") -> None:
        self.console.print(Panel(Text(message), title=title, border_style="cyan"))

    def success(self, message: str, *, title: str = "Done") -> None:
        self.console.print(Panel(Text(message), title=title, border_style="green"))

    def error(self, message: str, *, title: str = "Error") -> None:
        self.console.print(Panel(Text(message), title=title, border_style="red"))

    def _json_or_text(self, value: str) -> RenderableType:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return Text(value)
        return JSON.from_data(parsed)


def main(argv: list[str] | None = None) -> int:
    command = get_command(app)
    try:
        result = command.main(args=argv, prog_name="code-agent", standalone_mode=False)
        return int(result or 0)
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    except click.exceptions.Exit as exc:
        return int(exc.exit_code)
    except KeyboardInterrupt:
        TerminalRenderer(Console(stderr=True)).error("Interrupted")
        return 130
    except Exception as exc:
        TerminalRenderer(Console(stderr=True)).error(str(exc))
        return 1


@app.command()
def _main_command(
    workspace: Annotated[
        Path,
        typer.Option(
            "--workspace",
            help="Agent 可检查和修改的 workspace 路径。",
        ),
    ],
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            help="模型提供方。",
        ),
    ] = DEFAULT_PROVIDER,
    no_session: Annotated[
        bool,
        typer.Option(
            "--no-session",
            help="不写入会话日志。",
        ),
    ] = False,
) -> int:
    """针对单一 workspace 的交互式 AI 编程 Agent。"""

    if provider not in {"offline", "openai"}:
        raise typer.BadParameter("provider must be one of: offline, openai")
    return _interactive(workspace=workspace, provider=provider, no_session=no_session)


def _interactive(*, workspace: Path, provider: str, no_session: bool) -> int:
    renderer = TerminalRenderer(Console())
    config = AgentConfig(
        workspace_path=workspace,
        provider=provider,
    )
    agent = CodingAgent(config)

    while True:
        try:
            prompt = _read_input("code-agent> ")
        except EOFError:
            renderer.info("EOF received. Exiting.", title="Exit")
            return 0

        prompt = prompt.strip()
        if not prompt:
            continue
        if prompt in EXIT_COMMANDS:
            return 0
        if prompt == COMPACT_COMMAND:
            result = agent.compact_memory(
                save_session=not no_session,
                usage_logger=renderer.model_usage,
            )
            if result.compacted:
                fallback_note = " (fallback)" if result.used_fallback else ""
                renderer.info(result.summary, title=f"Compacted memory{fallback_note}")
            else:
                renderer.info("No older conversation to compact.", title="Memory")
            continue
        if prompt == MEMORY_COMMAND:
            renderer.info(agent.memory_status(), title="Memory")
            continue
        if prompt == CLEAR_COMMAND:
            agent.clear_memory()
            renderer.success("Memory cleared.", title="Memory")
            continue

        run = agent.run(
            prompt,
            shell_approval=_confirm_shell_command,
            event_logger=renderer.event,
            save_session=not no_session,
        )
        if run.session_path:
            renderer.info(str(run.session_path), title="Session")
        for model_call in run.model_calls:
            renderer.model_usage(model_call)


def _print_event(event: AgentEvent) -> None:
    TerminalRenderer(Console()).event(event)


def _format_token_count(value: int | None) -> str:
    if value is None:
        return "unknown"
    return str(value)


def _confirm_shell_command(command: str) -> bool:
    TerminalRenderer(Console()).info(command, title="Shell Command")
    answer = _read_input("Approve? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def _read_input(prompt: str) -> str:
    return read_prompt(prompt, commands=SLASH_COMMANDS)


if __name__ == "__main__":
    raise SystemExit(main())
