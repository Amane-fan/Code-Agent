from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Protocol

from code_agent.config import AgentConfig
from code_agent.models import AgentEvent, AgentRun, ToolResult, WorkspaceContext
from code_agent.providers import make_provider
from code_agent.session import SessionStore
from code_agent.tools import FileTools, ShellTool


ProviderFactory = Callable[[str], "ModelProvider"]
ShellApproval = Callable[[str], bool]
EventLogger = Callable[[AgentEvent], None]


class ModelProvider(Protocol):
    @property
    def name(self) -> str:
        ...

    def complete(self, prompt: str, context: WorkspaceContext, *, model: str) -> str:
        ...


@dataclass(frozen=True)
class ParsedResponse:
    think: str | None
    action_text: str | None
    final_answer: str | None
    fallback_answer: str | None


@dataclass(frozen=True)
class ActionCall:
    tool: str
    args: dict[str, Any]
    raw: str


def run_react_agent(
    config: AgentConfig,
    prompt: str,
    *,
    provider_factory: ProviderFactory = make_provider,
    shell_approval: ShellApproval | None = None,
    event_logger: EventLogger | None = None,
    save_session: bool = True,
) -> AgentRun:
    """执行一个独立 ReAct 会话，直到模型给出 final answer 或达到循环上限。"""

    provider = provider_factory(config.provider)
    context = WorkspaceContext(
        root=config.workspace_root,
        prompt=prompt,
        git_status="",
        files=[],
    )
    history: list[AgentEvent] = []
    _append(history, AgentEvent("task", prompt), event_logger)

    iterations = 0
    final_answer: str | None = None
    file_tools = FileTools(config.workspace_root)
    shell_tool = ShellTool(config.workspace_root)

    for iteration in range(1, config.max_iterations + 1):
        iterations = iteration
        response_text = provider.complete(
            _render_prompt(config.workspace_root, history),
            context,
            model=config.model,
        )
        parsed = _parse_response(response_text)
        if parsed.think:
            _append(history, AgentEvent("think", parsed.think), event_logger)

        if parsed.action_text is not None:
            action, parse_error = _parse_action(parsed.action_text)
            if action is None:
                _append(
                    history,
                    AgentEvent("action", parsed.action_text),
                    event_logger,
                )
                _append(
                    history,
                    _observation_event(parse_error),
                    event_logger,
                )
                continue

            _append(
                history,
                AgentEvent("action", action.raw, tool=action.tool, args=action.args),
                event_logger,
            )
            result = _execute_action(
                action,
                file_tools=file_tools,
                shell_tool=shell_tool,
                shell_approval=shell_approval,
            )
            _append(history, _observation_event(result), event_logger)
            continue

        final_answer = parsed.final_answer or parsed.fallback_answer or ""
        _append(history, AgentEvent("final_answer", final_answer), event_logger)
        break

    if final_answer is None:
        final_answer = (
            f"Stopped after maximum iteration limit ({config.max_iterations}) without a final answer."
        )
        _append(history, AgentEvent("final_answer", final_answer), event_logger)

    run = AgentRun(
        prompt=prompt,
        provider=provider.name,
        model=config.model,
        final_answer=final_answer,
        response_text=final_answer,
        history=history,
        iterations=iterations,
    )
    if save_session:
        session_path = SessionStore(config.session_dir).save(run)
        run = replace(run, session_path=session_path)
    return run


def _append(history: list[AgentEvent], event: AgentEvent, logger: EventLogger | None) -> None:
    history.append(event)
    if logger is not None:
        logger(event)


def _render_prompt(workspace_root: Path, history: list[AgentEvent]) -> str:
    tool_spec = (
        "You are running one independent ReAct task.\n"
        f"Workspace: {workspace_root}\n"
        "Only use these tools: read_file, write_file, edit_file, list_files, grep_search, run_shell.\n"
        "If you need a tool, output <think>short public reasoning</think> and exactly one "
        '<action>{"tool":"tool_name","args":{...}}</action>.\n'
        "If no tool is needed, output <think>short public reasoning</think> and "
        "<final_answer>answer</final_answer>.\n"
        "Tool schemas:\n"
        '- read_file: {"path": "relative/path"}\n'
        '- write_file: {"path": "relative/path", "content": "..."}\n'
        '- edit_file: {"path": "relative/path", "old_text": "...", "new_text": "..."}\n'
        "- list_files: {}\n"
        '- grep_search: {"pattern": "text"}\n'
        '- run_shell: {"command": "shell command"}\n'
        "History:\n"
    )
    return tool_spec + "\n".join(event.tag for event in history)


def _parse_response(text: str) -> ParsedResponse:
    think = _extract_tag(text, "think")
    action_text = _extract_tag(text, "action")
    final_answer = _extract_tag(text, "final_answer")
    fallback_answer = text.strip() if action_text is None and final_answer is None else None
    return ParsedResponse(think, action_text, final_answer, fallback_answer)


def _extract_tag(text: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, flags=re.DOTALL)
    if match is None:
        return None
    return match.group(1).strip()


def _parse_action(raw: str) -> tuple[ActionCall | None, ToolResult]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, ToolResult("action.parse", False, error=f"invalid action JSON: {exc}")
    if not isinstance(payload, dict):
        return None, ToolResult("action.parse", False, error="action must be a JSON object")
    tool = payload.get("tool")
    args = payload.get("args", {})
    if not isinstance(tool, str) or not tool:
        return None, ToolResult("action.parse", False, error="action.tool must be a non-empty string")
    if not isinstance(args, dict):
        return None, ToolResult("action.parse", False, error="action.args must be an object")
    normalized = json.dumps({"tool": tool, "args": args}, ensure_ascii=False, sort_keys=True)
    return ActionCall(tool=tool, args=args, raw=normalized), ToolResult("action.parse", True)


def _execute_action(
    action: ActionCall,
    *,
    file_tools: FileTools,
    shell_tool: ShellTool,
    shell_approval: ShellApproval | None,
) -> ToolResult:
    try:
        if action.tool == "read_file":
            return file_tools.read(_required_str(action, "path"))
        if action.tool == "write_file":
            return file_tools.write(_required_str(action, "path"), _required_str(action, "content"))
        if action.tool == "edit_file":
            return file_tools.edit(
                _required_str(action, "path"),
                _required_str(action, "old_text"),
                _required_str(action, "new_text"),
            )
        if action.tool == "list_files":
            return file_tools.list()
        if action.tool == "grep_search":
            return file_tools.search(_required_str(action, "pattern"))
        if action.tool == "run_shell":
            command = _required_str(action, "command")
            approved = shell_approval(command) if shell_approval is not None else False
            return shell_tool.run(command, approved=approved)
    except ValueError as exc:
        return ToolResult(action.tool, False, error=str(exc), metadata={"args": action.args})
    return ToolResult(action.tool, False, error=f"unknown tool: {action.tool}")


def _required_str(action: ActionCall, name: str) -> str:
    value = action.args.get(name)
    if not isinstance(value, str):
        raise ValueError(f"{action.tool}.{name} must be a string")
    return value


def _observation_event(result: ToolResult) -> AgentEvent:
    content = json.dumps(
        {
            "name": result.name,
            "ok": result.ok,
            "output": result.output,
            "error": result.error,
            "metadata": result.metadata,
        },
        ensure_ascii=False,
    )
    return AgentEvent("observation", content, tool=result.name, result=result)
