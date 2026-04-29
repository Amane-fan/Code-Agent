from __future__ import annotations

import argparse
import sys
from pathlib import Path

from code_agent.agent import CodingAgent
from code_agent.config import AgentConfig
from code_agent.context import collect_repo_context
from code_agent.tools import FileTools, ShellTool, detect_test_command


def main(argv: list[str] | None = None) -> int:
    # CLI 层只负责参数解析和展示，核心流程放在 CodingAgent 中保持可测试。
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "ask":
            return _ask(args)
        if args.command == "context":
            return _context(args)
        if args.command == "tool":
            return _tool(args)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="code-agent",
        description="Terminal-first AI coding agent for local repositories.",
    )
    subparsers = parser.add_subparsers(dest="command")

    ask = subparsers.add_parser(
        "ask",
        help="Ask the coding agent to inspect the repo and propose a change.",
    )
    ask.add_argument("prompt", help="Task for the coding agent.")
    ask.add_argument("--repo", default=".", help="Repository path.")
    ask.add_argument("--provider", default="offline", choices=["offline", "openai"])
    ask.add_argument(
        "--model",
        default=None,
        help="Model name. Defaults to OPENAI_MODEL or project default.",
    )
    ask.add_argument(
        "--apply",
        action="store_true",
        help="Apply a generated unified diff after validation.",
    )
    ask.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation for --apply.",
    )
    ask.add_argument(
        "--test",
        action="store_true",
        help="Run the detected test command after applying.",
    )
    ask.add_argument("--test-command", default=None, help="Override the detected test command.")
    ask.add_argument(
        "--unsafe",
        action="store_true",
        help="Allow a custom test command outside the safe list.",
    )
    ask.add_argument("--max-files", type=int, default=12)
    ask.add_argument("--no-session", action="store_true", help="Do not write a session log.")

    context = subparsers.add_parser(
        "context",
        help="Print the repo context that would be sent to a model.",
    )
    context.add_argument("prompt")
    context.add_argument("--repo", default=".")
    context.add_argument("--max-files", type=int, default=12)

    tool = subparsers.add_parser("tool", help="Run a local tool directly.")
    tool_subparsers = tool.add_subparsers(dest="tool_command")
    read = tool_subparsers.add_parser("read", help="Read a non-sensitive file.")
    read.add_argument("path")
    read.add_argument("--repo", default=".")
    search = tool_subparsers.add_parser("search", help="Search non-sensitive files.")
    search.add_argument("pattern")
    search.add_argument("--repo", default=".")
    list_files = tool_subparsers.add_parser("list", help="List non-sensitive files.")
    list_files.add_argument("--repo", default=".")
    run = tool_subparsers.add_parser("run", help="Run a safe shell command.")
    run.add_argument("shell_command")
    run.add_argument("--repo", default=".")
    run.add_argument("--unsafe", action="store_true")
    detect = tool_subparsers.add_parser("detect-test", help="Print the detected test command.")
    detect.add_argument("--repo", default=".")

    return parser


def _ask(args: argparse.Namespace) -> int:
    """执行一次完整的 Agent 请求。"""

    config = AgentConfig(
        repo_path=Path(args.repo),
        provider=args.provider,
        max_files=args.max_files,
        **({"model": args.model} if args.model else {}),
    )
    if args.apply and not args.yes:
        # 交互式确认是 --apply 的最后一道人为安全门。
        answer = input("Apply generated patch if validation passes? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Aborted before applying.")
            return 1

    run = CodingAgent(config).run(
        args.prompt,
        apply_patch=args.apply,
        run_tests=args.test,
        test_command=args.test_command,
        allow_unsafe_commands=args.unsafe,
        save_session=not args.no_session,
    )
    print(run.response_text)
    if run.patch:
        print("\nPatch: detected")
    if args.apply:
        print(f"Applied: {run.applied}")
    if run.test_result:
        print(f"\n{run.test_result.name}: {'ok' if run.test_result.ok else 'failed'}")
        if run.test_result.output:
            print(run.test_result.output)
        if run.test_result.error:
            print(run.test_result.error, file=sys.stderr)
    if run.session_path:
        print(f"\nSession: {run.session_path}")
    return 0 if not run.test_result or run.test_result.ok else 1


def _context(args: argparse.Namespace) -> int:
    """打印即将发送给模型的上下文，便于调试召回和敏感文件过滤。"""

    config = AgentConfig(repo_path=Path(args.repo), max_files=args.max_files)
    context = collect_repo_context(
        config.repo_root,
        args.prompt,
        max_files=config.max_files,
        max_file_bytes=config.max_file_bytes,
        max_context_chars=config.max_context_chars,
    )
    print(context.render(config.max_context_chars))
    return 0


def _tool(args: argparse.Namespace) -> int:
    """直接运行底层工具，便于单独验证安全策略和命令检测。"""

    repo = Path(getattr(args, "repo", ".")).expanduser().resolve()
    if args.tool_command == "read":
        result = FileTools(repo).read(args.path)
    elif args.tool_command == "search":
        result = FileTools(repo).search(args.pattern)
    elif args.tool_command == "list":
        result = FileTools(repo).list()
    elif args.tool_command == "run":
        result = ShellTool(repo).run(args.shell_command, allow_unsafe=args.unsafe)
    elif args.tool_command == "detect-test":
        command = detect_test_command(repo)
        print(command or "")
        return 0 if command else 1
    else:
        print("Missing tool command", file=sys.stderr)
        return 2

    if result.output:
        print(result.output)
    if result.error:
        print(result.error, file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
