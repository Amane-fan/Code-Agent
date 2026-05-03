from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Callable, Literal, Protocol, Sequence, TypedDict, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from code_agent.config import AgentConfig
from code_agent.models import (
    AgentEvent,
    AgentRun,
    ModelCallUsage,
    ModelCompletion,
    ModelToolCall,
    ToolResult,
    WorkspaceContext,
)
from code_agent.prompting import BASE_SYSTEM_TEMPLATE, build_system_instructions
from code_agent.providers import make_provider
from code_agent.session import SessionStore
from code_agent.skill_selection import select_skills
from code_agent.skills import SkillRegistry
from code_agent.tools import ToolRegistry, create_workspace_tool_registry


ProviderFactory = Callable[[str], "ModelProvider"]
ShellApproval = Callable[[str], bool]
EventLogger = Callable[[AgentEvent], None]


class ModelProvider(Protocol):
    @property
    def name(self) -> str:
        ...

    def complete(
        self,
        messages: Sequence[BaseMessage],
        *,
        model: str,
        tools: Sequence[BaseTool] | None = None,
    ) -> ModelCompletion:
        ...


@dataclass(frozen=True)
class ParsedFinalEvent:
    content: str
    summary: str = ""


class AgentGraphState(TypedDict):
    history: list[AgentEvent]
    context: WorkspaceContext
    provider: ModelProvider
    provider_name: str
    model: str
    system_instructions: str
    base_system_template: str
    skill_registry: SkillRegistry
    tool_registry: ToolRegistry | None
    shell_approval: ShellApproval | None
    event_logger: EventLogger | None
    max_iterations: int
    iterations: int
    final_answer: str | None
    pending_tool_calls: list[ModelToolCall]
    model_calls: list[ModelCallUsage]


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
    system_instructions: str | None = None,
) -> AgentRun:
    """执行一次 tool-calling ReAct 任务，可接收窗口级历史作为模型输入前缀。"""

    provider = provider_factory(config.provider)
    context = WorkspaceContext(
        root=config.workspace_root,
        prompt=prompt,
        git_status="",
        files=[],
    )
    history: list[AgentEvent] = list(initial_history or [])
    _append(history, _task_event(prompt), event_logger)

    graph = _build_react_graph()
    final_state = cast(
        AgentGraphState,
        graph.invoke(
            {
                "history": history,
                "context": context,
                "provider": provider,
                "provider_name": config.provider.lower().strip(),
                "model": config.model,
                "system_instructions": system_instructions or "",
                "base_system_template": BASE_SYSTEM_TEMPLATE,
                "skill_registry": skill_registry or SkillRegistry.empty(),
                "tool_registry": tool_registry,
                "shell_approval": shell_approval,
                "event_logger": event_logger,
                "max_iterations": config.max_iterations,
                "iterations": 0,
                "final_answer": None,
                "pending_tool_calls": [],
                "model_calls": [],
            }
        ),
    )

    run = AgentRun(
        prompt=prompt,
        provider=provider.name,
        model=config.model,
        final_answer=final_state["final_answer"] or "",
        response_text=final_state["final_answer"] or "",
        history=final_state["history"],
        iterations=final_state["iterations"],
        model_calls=final_state["model_calls"],
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
    graph.add_node("select_skills", _select_skills_node)
    graph.add_node("call_model", _call_model_node)
    graph.add_node("execute_tools", _execute_tools_node)
    graph.add_node("limit", _limit_node)
    graph.add_edge(START, "select_skills")
    graph.add_conditional_edges(
        "select_skills",
        _route_after_select_skills,
        {
            "call_model": "call_model",
            "limit": "limit",
        },
    )
    graph.add_conditional_edges(
        "call_model",
        _route_after_call_model,
        {
            "execute_tools": "execute_tools",
            "call_model": "call_model",
            "limit": "limit",
            "end": END,
        },
    )
    graph.add_conditional_edges(
        "execute_tools",
        _route_after_execute_tools,
        {
            "call_model": "call_model",
            "limit": "limit",
        },
    )
    graph.add_edge("limit", END)
    return graph.compile()


def _select_skills_node(state: AgentGraphState) -> dict[str, Any]:
    model_calls = list(state["model_calls"])
    loaded_skills = []
    full_skill_registry = state["skill_registry"]
    if state["provider_name"] != "offline" and full_skill_registry.names():
        result = select_skills(
            provider=state["provider"],
            model=state["model"],
            user_prompt=state["context"].prompt,
            history=state["history"],
            skill_registry=full_skill_registry,
        )
        loaded_skills = result.loaded_skills
        model_calls.extend(result.model_calls)

    selected_skill_registry = SkillRegistry.from_loaded(loaded_skills)
    tool_registry = state["tool_registry"] or create_workspace_tool_registry(
        state["context"].root,
        skill_registry=selected_skill_registry,
        shell_approval=state["shell_approval"],
    )
    system_instructions = state["system_instructions"] or build_system_instructions(
        tool_registry=tool_registry,
        skill_registry=full_skill_registry,
        loaded_skills=loaded_skills,
        workspace_root=state["context"].root,
        base_instructions=state["base_system_template"],
    )
    return {
        "tool_registry": tool_registry,
        "system_instructions": system_instructions,
        "model_calls": model_calls,
    }


def _call_model_node(state: AgentGraphState) -> dict[str, Any]:
    history = list(state["history"])
    model_calls = list(state["model_calls"])
    iteration = state["iterations"] + 1
    tool_registry = state["tool_registry"]
    if tool_registry is None:
        tool_registry = create_workspace_tool_registry(
            state["context"].root,
            skill_registry=SkillRegistry.empty(),
            shell_approval=state["shell_approval"],
        )

    response = state["provider"].complete(
        _messages_for_model(state["system_instructions"], history),
        model=state["model"],
        tools=tool_registry.tools,
    )
    completion = _normalize_completion(response)
    model_calls.append(
        ModelCallUsage(
            provider=state["provider"].name,
            model=state["model"],
            purpose="task",
            ok=True,
            usage=completion.usage,
            system_instructions=state["system_instructions"],
        )
    )

    if completion.tool_calls:
        summary = _summary_from_tool_call_content(completion.text)
        if summary:
            _append(history, _summary_event(summary), state["event_logger"])
        for tool_call in completion.tool_calls:
            _append(
                history,
                _tool_call_event(tool_call, reasoning_content=completion.reasoning_content),
                state["event_logger"],
            )
        return {
            "history": history,
            "iterations": iteration,
            "final_answer": None,
            "pending_tool_calls": completion.tool_calls,
            "model_calls": model_calls,
            "tool_registry": tool_registry,
        }

    parsed = _parse_final_event(completion.text)
    if parsed.summary:
        _append(history, _summary_event(parsed.summary), state["event_logger"])
    _append(history, _final_answer_event(parsed.content), state["event_logger"])
    return {
        "history": history,
        "iterations": iteration,
        "final_answer": parsed.content,
        "pending_tool_calls": [],
        "model_calls": model_calls,
        "tool_registry": tool_registry,
    }


def _execute_tools_node(state: AgentGraphState) -> dict[str, Any]:
    pending_tool_calls = state["pending_tool_calls"]
    tool_registry = state["tool_registry"]
    if not pending_tool_calls or tool_registry is None:
        return {"pending_tool_calls": []}

    history = list(state["history"])
    for tool_call in pending_tool_calls:
        result = tool_registry.execute(tool_call.name, tool_call.args)
        _append(history, _tool_result_event(tool_call, result), state["event_logger"])
    return {
        "history": history,
        "pending_tool_calls": [],
    }


def _limit_node(state: AgentGraphState) -> dict[str, Any]:
    history = list(state["history"])
    final_answer = (
        f"Stopped after maximum iteration limit ({state['max_iterations']}) without a final answer."
    )
    _append(history, _final_answer_event(final_answer), state["event_logger"])
    return {
        "history": history,
        "final_answer": final_answer,
        "pending_tool_calls": [],
        "model_calls": state["model_calls"],
    }


def _route_after_select_skills(state: AgentGraphState) -> Literal["call_model", "limit"]:
    if state["iterations"] >= state["max_iterations"]:
        return "limit"
    return "call_model"


def _route_after_call_model(
    state: AgentGraphState,
) -> Literal["execute_tools", "call_model", "limit", "end"]:
    if state["final_answer"] is not None:
        return "end"
    if state["pending_tool_calls"]:
        return "execute_tools"
    if state["iterations"] >= state["max_iterations"]:
        return "limit"
    return "call_model"


def _route_after_execute_tools(state: AgentGraphState) -> Literal["call_model", "limit"]:
    if state["iterations"] >= state["max_iterations"]:
        return "limit"
    return "call_model"


def _append(history: list[AgentEvent], event: AgentEvent, logger: EventLogger | None) -> None:
    history.append(event)
    if logger is not None:
        logger(event)


def _messages_for_model(system_instructions: str, history: list[AgentEvent]) -> list[BaseMessage]:
    messages: list[BaseMessage] = [SystemMessage(content=system_instructions)]
    index = 0
    while index < len(history):
        event = history[index]
        if event.type == "memory":
            messages.append(SystemMessage(content=event.to_json_line()))
        elif event.type == "task":
            messages.append(HumanMessage(content=event.to_json_line()))
        elif event.type in {"summary", "final_answer"}:
            messages.append(AIMessage(content=event.to_json_line()))
        elif event.type == "tool_call":
            tool_call_events, index = _collect_consecutive_tool_call_events(history, index)
            messages.append(_tool_call_message(tool_call_events))
            continue
        elif event.type == "tool_result":
            messages.append(
                ToolMessage(
                    content=event.content,
                    tool_call_id=event.call_id or "",
                    name=event.tool,
                )
            )
        index += 1
    return messages


def _collect_consecutive_tool_call_events(
    history: list[AgentEvent],
    start_index: int,
) -> tuple[list[AgentEvent], int]:
    events: list[AgentEvent] = []
    index = start_index
    while index < len(history) and history[index].type == "tool_call":
        events.append(history[index])
        index += 1
    return events, index


def _tool_call_message(events: list[AgentEvent]) -> AIMessage:
    tool_calls = [
        {
            "name": event.tool or "",
            "args": event.args,
            "id": event.call_id or "",
        }
        for event in events
    ]
    additional_kwargs: dict[str, Any] = {}
    reasoning_content = next(
        (event.reasoning_content for event in events if event.reasoning_content),
        "",
    )
    if reasoning_content:
        # thinking 模式模型要求工具结果回灌时带回该字段，但它不进入 CLI 展示内容。
        additional_kwargs["reasoning_content"] = reasoning_content
    return AIMessage(
        content="\n".join(event.content for event in events),
        tool_calls=tool_calls,
        additional_kwargs=additional_kwargs,
    )


def _normalize_completion(response: ModelCompletion | str) -> ModelCompletion:
    if isinstance(response, ModelCompletion):
        return response
    return ModelCompletion(text=response)


def _parse_final_event(text: str) -> ParsedFinalEvent:
    stripped = text.strip()
    if not stripped:
        return ParsedFinalEvent(content="")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return ParsedFinalEvent(content=stripped)

    if not isinstance(payload, dict):
        return ParsedFinalEvent(content=stripped)
    event_type = payload.get("type")
    content = payload.get("content")
    if event_type == "final_answer" and isinstance(content, str):
        return ParsedFinalEvent(content=content, summary=_optional_summary(payload))
    return ParsedFinalEvent(content=stripped)


def _optional_summary(payload: dict[str, Any]) -> str:
    summary = payload.get("summary")
    return summary if isinstance(summary, str) else ""


def _summary_from_tool_call_content(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if not isinstance(payload, dict):
        return stripped
    if payload.get("type") == "summary" and isinstance(payload.get("content"), str):
        return cast(str, payload["content"])
    return stripped


def _task_event(prompt: str) -> AgentEvent:
    return AgentEvent(role="user", type="task", content=prompt)


def _summary_event(content: str) -> AgentEvent:
    return AgentEvent(role="assistant", type="summary", content=content)


def _final_answer_event(content: str) -> AgentEvent:
    return AgentEvent(role="assistant", type="final_answer", content=content)


def _tool_call_event(tool_call: ModelToolCall, *, reasoning_content: str = "") -> AgentEvent:
    content = json.dumps(
        {
            "role": "assistant",
            "type": "tool_call",
            "tool": tool_call.name,
            "call_id": tool_call.id,
            "args": tool_call.args,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return AgentEvent(
        role="assistant",
        type="tool_call",
        content=content,
        tool=tool_call.name,
        call_id=tool_call.id,
        args=tool_call.args,
        reasoning_content=reasoning_content,
    )


def _tool_result_event(tool_call: ModelToolCall, result: ToolResult) -> AgentEvent:
    content = json.dumps(
        {
            "role": "tool",
            "type": "tool_result",
            "tool": tool_call.name,
            "call_id": tool_call.id,
            "ok": result.ok,
            "output": result.output,
            "error": result.error,
            "metadata": result.metadata,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return AgentEvent(
        role="tool",
        type="tool_result",
        content=content,
        tool=tool_call.name,
        call_id=tool_call.id,
        result=result,
    )
