from __future__ import annotations

import argparse
import sys
from pathlib import Path

from code_agent.agent import CodingAgent
from code_agent.config import DEFAULT_PROVIDER, AgentConfig
from code_agent.models import AgentEvent
from code_agent.terminal import enable_line_editing, preserve_stdin_terminal


EXIT_COMMANDS = {"/exit", "/quit"}
COMPACT_COMMAND = "/compact"
CLEAR_COMMAND = "/clear"
MEMORY_COMMAND = "/memory"


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    try:
        return _interactive(args)
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code-agent",
        description="Interactive AI coding agent for a single workspace.",
    )
    parser.add_argument(
        "--workspace",
        required=True,
        help="Workspace path the agent may inspect and modify.",
    )
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, choices=["offline", "openai"])
    parser.add_argument("--no-session", action="store_true", help="Do not write session logs.")
    return parser


def _interactive(args: argparse.Namespace) -> int:
    enable_line_editing()
    config = AgentConfig(
        workspace_path=Path(args.workspace),
        provider=args.provider,
    )
    agent = CodingAgent(config)

    while True:
        try:
            prompt = _read_input("code-agent> ")
        except EOFError:
            print()
            return 0

        prompt = prompt.strip()
        if not prompt:
            continue
        if prompt in EXIT_COMMANDS:
            return 0
        if prompt == COMPACT_COMMAND:
            result = agent.compact_memory()
            if result.compacted:
                fallback_note = " (fallback)" if result.used_fallback else ""
                print(f"Compacted memory{fallback_note}:")
                print(result.summary)
            else:
                print("No older conversation to compact.")
            continue
        if prompt == MEMORY_COMMAND:
            print(agent.memory_status())
            continue
        if prompt == CLEAR_COMMAND:
            agent.clear_memory()
            print("Memory cleared.")
            continue

        run = agent.run(
            prompt,
            shell_approval=_confirm_shell_command,
            event_logger=_print_event,
            save_session=not args.no_session,
        )
        if run.session_path:
            print(f"\nSession: {run.session_path}")


def _print_event(event: AgentEvent) -> None:
    print(event.tag)


def _confirm_shell_command(command: str) -> bool:
    answer = _read_input(f"Run shell command? {command}\nApprove? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def _read_input(prompt: str) -> str:
    with preserve_stdin_terminal():
        return input(prompt)


if __name__ == "__main__":
    raise SystemExit(main())
