import argparse
import json
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from rich.console import Console

from terminal_code_agent.config import load_settings
from terminal_code_agent.graph import build_graph
from terminal_code_agent.logging_utils import JsonlLogger
from terminal_code_agent.schemas import ApprovalResume, PendingToolCall

console = Console()


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
    return f"- {call.get('name')} {compact}"


def ask_user_for_approval(payload: dict[str, Any]) -> dict[str, Any]:
    """CLI 审批入口；只处理 y/n/edit，不在 graph 节点中读取 stdin。"""

    console.print(f"[gate] {payload.get('question', '是否允许执行工具调用？')}")
    console.print(f"[gate] risk={payload.get('risk', '')}")
    for call in payload.get("tool_calls", []):
        console.print(_summarize_call(call))

    while True:
        answer = input("是否批准？y/n/edit > ").strip().lower()
        if answer in {"y", "yes"}:
            return ApprovalResume(decision="approved").model_dump()
        if answer in {"n", "no"}:
            return ApprovalResume(decision="rejected").model_dump()
        if answer in {"e", "edit"}:
            raw = input("请输入 edited_tool_calls JSON > ").strip()
            try:
                edited = [PendingToolCall.model_validate(item) for item in json.loads(raw)]
            except Exception as exc:
                console.print(f"编辑内容无效: {exc}")
                continue
            return ApprovalResume(decision="approved", edited_tool_calls=edited).model_dump()
        console.print("请输入 y、n 或 edit。")


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
    final_json = result.get("final_json", result)
    console.print(json.dumps(final_json, ensure_ascii=False, indent=2))


def main() -> None:
    args = parse_args()
    settings = load_settings(args.env_file)
    if args.log_level:
        settings.log_level = args.log_level
    workdir = resolve_workdir(args.workdir)
    logger = JsonlLogger(settings.log_dir, level=settings.log_level)
    graph = build_graph(InMemorySaver(), settings=settings, logger=logger)
    config = {"configurable": {"thread_id": args.thread_id}}

    while True:
        try:
            user_input = input("user> ").strip()
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
