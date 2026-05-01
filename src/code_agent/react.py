from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any, Callable, Literal, Protocol, Sequence, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from code_agent.config import AgentConfig
from code_agent.models import AgentEvent, AgentRun, ToolResult, WorkspaceContext
from code_agent.providers import make_provider
from code_agent.session import SessionStore
from code_agent.skills import SkillRegistry
from code_agent.tools import ToolRegistry, create_workspace_tool_registry


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
    summary: str | None
    action_text: str | None
    final_answer: str | None
    fallback_answer: str | None


@dataclass(frozen=True)
class ActionCall:
    tool: str
    args: dict[str, Any]
    raw: str


class AgentGraphState(TypedDict):
    history: list[AgentEvent]
    context: WorkspaceContext
    provider: ModelProvider
    model: str
    tool_registry: ToolRegistry
    event_logger: EventLogger | None
    max_iterations: int
    iterations: int
    final_answer: str | None
    pending_action: ActionCall | None


def run_react_agent(
    config: AgentConfig,
    prompt: str,
    *,
    provider_factory: ProviderFactory = make_provider,
    shell_approval: ShellApproval | None = None,
    event_logger: EventLogger | None = None,
    save_session: bool = True,
    initial_history: Sequence[AgentEvent] | None = None,
    session_store: SessionStore | None = None,
    skill_registry: SkillRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
) -> AgentRun:
    """执行一次 ReAct 任务，可接收窗口级历史作为模型输入前缀。"""

    provider = provider_factory(config.provider)
    context = WorkspaceContext(
        root=config.workspace_root,
        prompt=prompt,
        git_status="",
        files=[],
    )
    history: list[AgentEvent] = list(initial_history or [])
    _append(history, AgentEvent("task", prompt), event_logger)

    iterations = 0
    final_answer: str | None = None
    tools = tool_registry or create_workspace_tool_registry(
        config.workspace_root,
        skill_registry=skill_registry,
        shell_approval=shell_approval,
    )

    graph = _build_react_graph()
    final_state = cast(
        AgentGraphState,
        graph.invoke(
            {
                "history": history,
                "context": context,
                "provider": provider,
                "model": config.model,
                "tool_registry": tools,
                "event_logger": event_logger,
                "max_iterations": config.max_iterations,
                "iterations": iterations,
                "final_answer": final_answer,
                "pending_action": None,
            }
        ),
    )
    history = final_state["history"]
    iterations = final_state["iterations"]
    final_answer = final_state["final_answer"] or ""

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
        store = session_store or SessionStore(config.session_dir)
        session_path = store.save(run)
        run = replace(run, session_path=session_path)
    return run


def _build_react_graph() -> CompiledStateGraph[
    AgentGraphState, None, AgentGraphState, AgentGraphState
]:
    graph = StateGraph(AgentGraphState)
    graph.add_node("call_model", _call_model_node)
    graph.add_node("execute_tool", _execute_tool_node)
    graph.add_node("limit", _limit_node)
    graph.add_conditional_edges(
        START,
        _route_from_start,
        {
            "call_model": "call_model",
            "limit": "limit",
        },
    )
    graph.add_conditional_edges(
        "call_model",
        _route_after_call_model,
        {
            "execute_tool": "execute_tool",
            "call_model": "call_model",
            "limit": "limit",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "execute_tool",
        _route_after_execute_tool,
        {
            "call_model": "call_model",
            "limit": "limit",
        },
    )
    graph.add_edge("limit", END)
    return graph.compile()


def _call_model_node(state: AgentGraphState) -> dict[str, Any]:
    history = list(state["history"])
    iteration = state["iterations"] + 1
    response_text = state["provider"].complete(
        _render_prompt(history),
        state["context"],
        model=state["model"],
    )
    parsed = _parse_response(response_text)
    if parsed.summary:
        _append(history, AgentEvent("summary", parsed.summary), state["event_logger"])

    if parsed.action_text is not None:
        action, parse_error = _parse_action(parsed.action_text)
        if action is None:
            _append(
                history,
                AgentEvent("action", parsed.action_text),
                state["event_logger"],
            )
            _append(
                history,
                _observation_event(parse_error),
                state["event_logger"],
            )
            return {
                "history": history,
                "iterations": iteration,
                "final_answer": None,
                "pending_action": None,
            }

        _append(
            history,
            AgentEvent("action", action.raw, tool=action.tool, args=action.args),
            state["event_logger"],
        )
        return {
            "history": history,
            "iterations": iteration,
            "final_answer": None,
            "pending_action": action,
        }

    final_answer = parsed.final_answer or parsed.fallback_answer or ""
    _append(history, AgentEvent("final_answer", final_answer), state["event_logger"])
    return {
        "history": history,
        "iterations": iteration,
        "final_answer": final_answer,
        "pending_action": None,
    }


def _execute_tool_node(state: AgentGraphState) -> dict[str, Any]:
    action = state["pending_action"]
    if action is None:
        return {"pending_action": None}

    history = list(state["history"])
    result = _execute_action(
        action,
        tool_registry=state["tool_registry"],
    )
    _append(history, _observation_event(result), state["event_logger"])
    return {
        "history": history,
        "pending_action": None,
    }


def _limit_node(state: AgentGraphState) -> dict[str, Any]:
    history = list(state["history"])
    final_answer = (
        f"Stopped after maximum iteration limit ({state['max_iterations']}) without a final answer."
    )
    _append(history, AgentEvent("final_answer", final_answer), state["event_logger"])
    return {
        "history": history,
        "final_answer": final_answer,
        "pending_action": None,
    }


def _route_from_start(state: AgentGraphState) -> Literal["call_model", "limit"]:
    if state["iterations"] >= state["max_iterations"]:
        return "limit"
    return "call_model"


def _route_after_call_model(
    state: AgentGraphState,
) -> Literal["execute_tool", "call_model", "limit", "end"]:
    if state["final_answer"] is not None:
        return "end"
    if state["pending_action"] is not None:
        return "execute_tool"
    if state["iterations"] >= state["max_iterations"]:
        return "limit"
    return "call_model"


def _route_after_execute_tool(state: AgentGraphState) -> Literal["call_model", "limit"]:
    if state["iterations"] >= state["max_iterations"]:
        return "limit"
    return "call_model"


def _append(history: list[AgentEvent], event: AgentEvent, logger: EventLogger | None) -> None:
    history.append(event)
    if logger is not None:
        logger(event)


def _render_prompt(history: list[AgentEvent]) -> str:
    return "\n".join(event.tag for event in history)


def _parse_response(text: str) -> ParsedResponse:
    summary = _extract_tag(text, "summary")
    action_text = _extract_tag(text, "action")
    final_answer = _extract_tag(text, "final_answer") or _extract_open_tag_to_end(
        text,
        "final_answer",
    )
    fallback_answer = text.strip() if action_text is None and final_answer is None else None
    return ParsedResponse(summary, action_text, final_answer, fallback_answer)


def _extract_tag(text: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, flags=re.DOTALL)
    if match is None:
        return None
    return match.group(1).strip()


def _extract_open_tag_to_end(text: str, tag: str) -> str | None:
    match = re.search(rf"<{tag}>(.*)\Z", text, flags=re.DOTALL)
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
    tool_registry: ToolRegistry,
) -> ToolResult:
    return tool_registry.execute(action.tool, action.args)


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
