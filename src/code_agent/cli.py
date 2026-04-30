from __future__ import annotations

import argparse
import sys
from pathlib import Path

from code_agent.agent import CodingAgent
from code_agent.config import DEFAULT_PROVIDER, AgentConfig
from code_agent.models import AgentEvent


EXIT_COMMANDS = {"/exit", "/quit"}


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
    config = AgentConfig(
        workspace_path=Path(args.workspace),
        provider=args.provider,
    )
    agent = CodingAgent(config)

    while True:
        try:
            prompt = input("code-agent> ")
        except EOFError:
            print()
            return 0

        prompt = prompt.strip()
        if not prompt:
            continue
        if prompt in EXIT_COMMANDS:
            return 0

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
    answer = input(f"Run shell command? {command}\nApprove? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


if __name__ == "__main__":
    raise SystemExit(main())
