from __future__ import annotations

import argparse
import sys
from pathlib import Path

from code_agent.agent import CodingAgent
from code_agent.config import DEFAULT_PROVIDER, AgentConfig
from code_agent.models import ToolResult
from code_agent.patches import PatchTool


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
    parser.add_argument("--max-files", type=int, default=12)
    parser.add_argument("--no-session", action="store_true", help="Do not write session logs.")
    parser.add_argument(
        "--unsafe",
        action="store_true",
        help="Allow unsafe shell commands for future workspace-bound test execution.",
    )
    return parser


def _interactive(args: argparse.Namespace) -> int:
    config = AgentConfig(
        workspace_path=Path(args.workspace),
        provider=args.provider,
        max_files=args.max_files,
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
            apply_patch=False,
            run_tests=False,
            allow_unsafe_commands=args.unsafe,
            save_session=not args.no_session,
        )
        print(run.response_text)
        if run.patch:
            _handle_patch(config, run.patch)
        if run.session_path:
            print(f"\nSession: {run.session_path}")


def _handle_patch(config: AgentConfig, patch: str) -> bool:
    tool = PatchTool(config.workspace_root)
    print("\nPatch: detected")
    check = tool.check(patch)
    if not check.ok:
        print("Patch check: failed")
        _print_tool_result(check)
        return False

    print("Patch check: ok")
    answer = input("Apply patch? [y/N] ").strip().lower()
    if answer not in {"y", "yes"}:
        print("Patch not applied.")
        return False

    applied = tool.apply(patch)
    if applied.ok:
        print("Patch applied.")
        return True

    print("Patch apply: failed")
    _print_tool_result(applied)
    return False


def _print_tool_result(result: ToolResult) -> None:
    if result.output:
        print(result.output)
    if result.error:
        print(result.error, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
