import json
import uuid
from pathlib import Path
from typing import Any, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from rich.console import Console
from rich.text import Text

from terminal_code_agent.config import Settings
from terminal_code_agent.llm import build_chat_model
from terminal_code_agent.logging_utils import JsonlLogger
from terminal_code_agent.prompts import (
    COMPACT_CONTEXT_PROMPT,
    REACT_SYSTEM_PROMPT,
    SKILL_SELECT_PROMPT,
)
from terminal_code_agent.schemas import (
    ApprovalRequest,
    PendingToolCall,
    SkillSelection,
    fallback_answer,
    parse_approval_resume,
)
from terminal_code_agent.state import AgentState, ChatRecord
from terminal_code_agent.token_budget import (
    compute_token_budget,
    estimate_tokens,
    pack_for_estimation,
)
from terminal_code_agent.tool_gate import evaluate_tool_calls
from terminal_code_agent.tool_runtime import parse_tool_result, truncate_text
from terminal_code_agent.tools import TOOL_BY_NAME, TOOLS, invoke_tool, summarize_tool_result

event_console = Console()


def _message_from_record(record: ChatRecord) -> BaseMessage:
    role = record.get("role", "user")
    content = record.get("content", "")
    if role == "assistant":
        metadata = record.get("metadata") or {}
        additional_kwargs: dict[str, Any] = {}
        if "reasoning_content" in metadata:
            additional_kwargs["reasoning_content"] = metadata["reasoning_content"]
        tool_calls = metadata.get("tool_calls")
        if tool_calls:
            return AIMessage(
                content=content, additional_kwargs=additional_kwargs, tool_calls=tool_calls
            )
        return AIMessage(content=content, additional_kwargs=additional_kwargs)
    if role == "tool":
        return ToolMessage(content=content, tool_call_id=record.get("tool_call_id") or "tool_call")
    if role in {"system", "developer"}:
        return SystemMessage(content=content)
    return HumanMessage(content=content)


def _message_to_record(message: Any) -> ChatRecord:
    content = str(getattr(message, "content", ""))
    record: ChatRecord = {"role": "assistant", "content": content}
    reasoning_content = (getattr(message, "additional_kwargs", {}) or {}).get("reasoning_content")
    if reasoning_content is not None:
        record["metadata"] = {"reasoning_content": str(reasoning_content)}
    return record


def _strip_reasoning_content(record: ChatRecord) -> ChatRecord:
    metadata = dict(record.get("metadata") or {})
    if "reasoning_content" not in metadata:
        return record
    metadata.pop("reasoning_content", None)
    sanitized = dict(record)
    if metadata:
        sanitized["metadata"] = metadata
    else:
        sanitized.pop("metadata", None)
    return cast(ChatRecord, sanitized)


def _clear_stale_reasoning_content(records: list[ChatRecord]) -> list[ChatRecord]:
    last_user_index = -1
    for index, record in enumerate(records):
        if record.get("role") == "user":
            last_user_index = index
    if last_user_index == -1:
        return [_strip_reasoning_content(record) for record in records]
    return [
        record if index >= last_user_index else _strip_reasoning_content(record)
        for index, record in enumerate(records)
    ]


def _tool_denial_messages(calls: list[dict[str, Any]], reason: str) -> list[ChatRecord]:
    messages: list[ChatRecord] = []
    for index, call in enumerate(calls):
        messages.append(
            {
                "role": "tool",
                "content": reason,
                "tool_call_id": str(call.get("id") or f"call_{index}"),
                "name": str(call.get("name") or "unknown_tool"),
            }
        )
    return messages


def _trim_leading_tool_messages(records: list[ChatRecord]) -> list[ChatRecord]:
    first_non_tool = 0
    while first_non_tool < len(records) and records[first_non_tool].get("role") == "tool":
        first_non_tool += 1
    return records[first_non_tool:]


def _state_settings(state: AgentState, settings: Settings) -> Settings:
    return settings


def _log(
    logger: JsonlLogger | None,
    state: AgentState,
    event: str,
    node: str,
    data: dict[str, Any] | None = None,
) -> None:
    if logger is None:
        return
    logger.event(
        event,
        run_id=state.get("run_id", ""),
        thread_id=state.get("thread_id", ""),
        node=node,
        data=data or {},
    )


def _print_event(text: str) -> None:
    event_console.print(Text(text, style="dim"))


def configure_event_console(*, no_color: bool = False) -> None:
    global event_console
    event_console = Console(no_color=no_color)


def init_state(state: AgentState, *, logger: JsonlLogger | None = None) -> dict[str, Any]:
    workdir = str(Path(state["workdir"]).resolve())
    run_id = str(uuid.uuid4())
    update = {
        "run_id": run_id,
        "workdir": workdir,
        "messages": [{"role": "user", "content": state["user_input"]}],
        "pending_tool_calls": [],
        "approved_tool_calls": [],
        "denied_tool_calls": [],
        "tool_results": [],
        "observations": [],
        "approval_result": "none",
        "tool_error": {},
        "tool_execute_status": "success",
        "force_final": False,
    }
    _print_event(f"[run] run_id={run_id} workdir={workdir}")
    if logger:
        logger.event(
            "run_start",
            run_id=run_id,
            thread_id=state.get("thread_id", ""),
            node="init_state",
            data=update,
        )
    return update


def _scan_skills(settings: Settings) -> list[dict[str, str]]:
    skills_root = settings.skills_dir
    if not skills_root.exists():
        return []
    items: list[dict[str, str]] = []
    for skill_dir in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        metadata = _parse_skill_metadata(skill_md.read_text(encoding="utf-8", errors="replace"))
        if metadata is None:
            continue
        items.append(
            {
                "name": metadata["name"],
                "description": metadata["description"],
                "path": str(skill_md),
            }
        )
    return items


def _parse_skill_metadata(content: str) -> dict[str, str] | None:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        return None
    metadata: dict[str, str] = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        if separator != ":":
            continue
        key = key.strip()
        value = value.strip().strip("\"'")
        if key in {"name", "description"}:
            metadata[key] = value
    if not metadata.get("name") or not metadata.get("description"):
        return None
    return metadata


def skill_select(
    state: AgentState, *, settings: Settings, model: Any = None, logger: JsonlLogger | None = None
) -> dict[str, Any]:
    skills = _scan_skills(settings)
    if not skills:
        _print_event('[decision] selected_skills=[] reason="skills 目录不存在或为空"')
        return {
            "selected_skills": [],
            "skill_context": "",
            "skill_reason": "skills 目录不存在或为空",
        }
    available = "\n".join(f"- {item['name']}: {item['description']}" for item in skills)
    selection = SkillSelection(selected_skills=[], reason="未选择 skill")
    if model is None:
        model = build_chat_model(settings)
    if model is not None:
        try:
            response = model.invoke(
                SKILL_SELECT_PROMPT.format_messages(
                    user_input=state["user_input"], available_skills=available
                )
            )
            selection = SkillSelection.model_validate(json.loads(str(response.content)))
        except Exception:
            selection = SkillSelection(selected_skills=[], reason="skill 选择解析失败，使用空列表")
    selected = [
        name for name in selection.selected_skills if any(item["name"] == name for item in skills)
    ][:3]
    contexts: list[str] = []
    skill_by_name = {item["name"]: item for item in skills}
    for name in selected:
        skill_file = Path(skill_by_name[name]["path"])
        content = skill_file.read_text(encoding="utf-8", errors="replace")
        contexts.append(f"# {name}\n{content[:8000]}")
    _print_event(f"[decision] selected_skills={selected} reason={selection.reason!r}")
    _log(
        logger,
        state,
        "skill_select",
        "skill_select",
        {"selected_skills": selected, "reason": selection.reason},
    )
    return {
        "selected_skills": selected,
        "skill_context": "\n\n".join(contexts),
        "skill_reason": selection.reason,
    }


def context_pack(state: AgentState, *, settings: Settings) -> dict[str, Any]:
    recent_messages = _trim_leading_tool_messages(state.get("messages", [])[-30:])
    recent_messages = _clear_stale_reasoning_content(recent_messages)
    observations = state.get("observations", [])[-10:]
    packed = pack_for_estimation(
        {
            "messages": recent_messages,
            "context_summary": state.get("context_summary", ""),
            "selected_skills": state.get("selected_skills", []),
            "skill_context": state.get("skill_context", ""),
            "observations": observations,
            "tool_error": state.get("tool_error", {}),
        }
    )
    estimated = estimate_tokens(packed, settings.model_name)
    return {
        "context_messages": recent_messages,
        "packed_context": packed,
        "estimated_tokens": estimated,
    }


def budget_check(
    state: AgentState, *, settings: Settings, logger: JsonlLogger | None = None
) -> dict[str, Any]:
    budget = compute_token_budget(
        settings.model_context_window, settings.model_max_tokens, settings.token_budget_ratio
    )
    status = "ok" if state.get("estimated_tokens", 0) <= budget else "over_limit"
    _print_event(
        f"[decision] budget {status}: estimated={state.get('estimated_tokens', 0)} budget={budget}"
    )
    _log(
        logger,
        state,
        "budget_check",
        "budget_check",
        {"estimated": state.get("estimated_tokens", 0), "budget": budget, "status": status},
    )
    return {"token_budget": budget, "budget_status": status}


def compact_context(state: AgentState, *, settings: Settings, model: Any = None) -> dict[str, Any]:
    attempts = state.get("compact_attempts", 0)
    if attempts >= settings.max_compact_attempts or model is None:
        return {
            "force_final": True,
            "final_answer": fallback_answer("上下文超过预算，已停止继续调用模型。"),
        }
    response = model.invoke(
        COMPACT_CONTEXT_PROMPT.format_messages(context=state.get("packed_context", ""))
    )
    return {"context_summary": str(response.content), "compact_attempts": attempts + 1}


def _format_model_info(settings: Settings) -> str:
    return "\n".join(
        [
            f"- model_name: {settings.model_name}",
            f"- model_temperature: {settings.model_temperature}",
            f"- model_max_tokens: {settings.model_max_tokens}",
            f"- model_context_window: {settings.model_context_window}",
            f"- model_timeout_seconds: {settings.model_timeout_seconds}",
        ]
    )


def _build_prompt_messages(state: AgentState, settings: Settings) -> list[BaseMessage]:
    messages = state.get("messages", [])
    context_messages = state.get("context_messages") or []
    records = cast(
        list[ChatRecord],
        context_messages if len(context_messages) == len(messages) else messages[-30:],
    )
    records = _trim_leading_tool_messages(records)
    records = _clear_stale_reasoning_content(records)
    history = [_message_from_record(record) for record in records]
    return REACT_SYSTEM_PROMPT.format_messages(
        workdir=state.get("workdir", ""),
        model_info=_format_model_info(settings),
        selected_skills=", ".join(state.get("selected_skills", [])),
        skill_context=state.get("skill_context", ""),
        context_summary=state.get("context_summary", ""),
        observations=json.dumps(state.get("observations", [])[-10:], ensure_ascii=False),
        tool_error=json.dumps(state.get("tool_error", {}), ensure_ascii=False),
        tool_names=", ".join(TOOL_BY_NAME),
        messages=history,
    )


def call_model(
    state: AgentState, *, settings: Settings, model: Any = None, logger: JsonlLogger | None = None
) -> dict[str, Any]:
    if state.get("force_final"):
        return {"model_route": "final"}
    if model is None:
        model = build_chat_model(settings)
    bound_model = model.bind_tools(TOOLS) if hasattr(model, "bind_tools") else model
    response = bound_model.invoke(_build_prompt_messages(state, settings))
    tool_calls = getattr(response, "tool_calls", None) or []
    content = str(getattr(response, "content", ""))
    reasoning_content = (getattr(response, "additional_kwargs", {}) or {}).get("reasoning_content")
    update: dict[str, Any] = {
        "llm_calls": state.get("llm_calls", 0) + 1,
        "model_response": {"content": content},
    }
    if tool_calls:
        pending = []
        for index, call in enumerate(tool_calls):
            pending.append(
                {
                    "id": call.get("id") or f"call_{index}",
                    "name": call.get("name"),
                    "args": call.get("args") or {},
                    "raw": call,
                }
            )
        names = ", ".join(call["name"] for call in pending)
        _print_event(f"[model] tool_calls={names}")
        metadata: dict[str, Any] = {
            "tool_calls": [
                {"id": call["id"], "name": call["name"], "args": call["args"]}
                for call in pending
            ]
        }
        if reasoning_content is not None:
            metadata["reasoning_content"] = str(reasoning_content)
        update.update(
            {
                "pending_tool_calls": pending,
                "model_route": "tool_calls",
                "messages": [
                    {
                        "role": "assistant",
                        "content": content,
                        "metadata": metadata,
                    }
                ],
            }
        )
        return update
    update.update(
        {
            "final_answer": content,
            "model_route": "final",
            "messages": [_message_to_record(response)],
        }
    )
    _log(logger, state, "call_model", "call_model", {"route": update["model_route"]})
    return update


def tool_gate(state: AgentState, *, settings: Settings) -> dict[str, Any]:
    result = evaluate_tool_calls(
        state.get("pending_tool_calls", []), settings=settings, workdir=state["workdir"]
    )
    route = result["tool_gate_route"]
    if route == "allowed":
        _print_event(
            f"[gate] allowed={[call['name'] for call in result.get('approved_tool_calls', [])]}"
        )
    elif route == "needs_approval":
        _print_event(f"[gate] needs_approval risk={result['approval_request'].get('risk')!r}")
    else:
        _print_event(f"[gate] denied={result.get('denied_tool_calls', [])}")
        reason = f"工具调用被拒绝：{result.get('denied_tool_calls', [])}。请重新规划。"
        result["messages"] = _tool_denial_messages(state.get("pending_tool_calls", []), reason)
    return result


def human_approval(state: AgentState) -> dict[str, Any]:
    request = ApprovalRequest.model_validate(state["approval_request"])
    resume_value = interrupt(request.model_dump())
    decision = parse_approval_resume(resume_value)
    if decision.decision == "approved":
        approved = decision.edited_tool_calls or request.tool_calls
        return {
            "approval_result": "approved",
            "approved_tool_calls": [call.model_dump() for call in approved],
        }
    return {
        "approval_result": "rejected",
        "messages": _tool_denial_messages(
            state.get("pending_tool_calls", []), "用户拒绝了工具调用。请基于拒绝结果重新规划。"
        ),
    }


def tool_execute(state: AgentState, *, settings: Settings) -> dict[str, Any]:
    calls = [PendingToolCall.model_validate(call) for call in state.get("approved_tool_calls", [])]
    results: list[dict[str, Any]] = []
    messages: list[ChatRecord] = []
    changed_files: list[str] = []
    commands_run: list[str] = []
    status = "success"
    tool_error: dict[str, Any] = {}
    for call in calls:
        raw = invoke_tool(call.name, call.args, workdir=state["workdir"], settings=settings)
        parsed = parse_tool_result(raw)
        results.append(parsed.model_dump())
        messages.append(
            {"role": "tool", "content": raw, "tool_call_id": call.id, "name": call.name}
        )
        _print_event(f"[tool] {call.name} {'success' if parsed.ok else parsed.error_type}")
        if call.name == "run_shell":
            commands_run.append(str(call.args.get("command", "")))
        changed_files.extend(
            parsed.metadata.get("changed_files", []) or parsed.data.get("changed_files", [])
        )
        if not parsed.ok:
            status = parsed.error_type or "retryable_error"
            tool_error = parsed.model_dump()
            break
    return {
        "tool_results": results,
        "messages": messages,
        "tool_execute_status": status,
        "tool_error": tool_error,
        "changed_files": changed_files,
        "commands_run": commands_run,
    }


def observe(state: AgentState, *, settings: Settings) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for result in state.get("tool_results", []):
        raw = json.dumps(result, ensure_ascii=False)
        summary = summarize_tool_result(raw)
        observations.append(summary)
    text, _ = truncate_text(
        json.dumps(observations, ensure_ascii=False), settings.max_context_chars_per_tool_result
    )
    _print_event(f"[observe] {text}")
    return {
        "observations": observations,
        "messages": [{"role": "assistant", "content": f"工具观察：{text}"}],
    }


def final_answer(state: AgentState, *, logger: JsonlLogger | None = None) -> dict[str, Any]:
    final = state.get("final_answer") or fallback_answer("本轮已结束。")
    _print_event("[final] done")
    _log(logger, state, "final_answer", "final_answer", {"answer": final})
    return {"final_answer": final}


def route_budget_check(state: AgentState) -> str:
    return state.get("budget_status", "ok")


def route_model_result(state: AgentState) -> str:
    return state.get("model_route", "final")


def route_tool_gate(state: AgentState) -> str:
    return state.get("tool_gate_route", "denied")


def route_human_approval(state: AgentState) -> str:
    return state.get("approval_result", "rejected")


def route_tool_execute(state: AgentState) -> str:
    return state.get("tool_execute_status", "fatal_error")


def build_graph(
    checkpointer: Any = None,
    *,
    settings: Settings | None = None,
    model: Any = None,
    logger: JsonlLogger | None = None,
):
    settings = settings or Settings()
    builder = StateGraph(AgentState)

    builder.add_node("init_state", lambda state: init_state(state, logger=logger))
    builder.add_node(
        "skill_select",
        lambda state: skill_select(state, settings=settings, model=model, logger=logger),
    )
    builder.add_node("context_pack", lambda state: context_pack(state, settings=settings))
    builder.add_node(
        "budget_check", lambda state: budget_check(state, settings=settings, logger=logger)
    )
    builder.add_node(
        "compact_context", lambda state: compact_context(state, settings=settings, model=model)
    )
    builder.add_node(
        "call_model", lambda state: call_model(state, settings=settings, model=model, logger=logger)
    )
    builder.add_node("tool_gate", lambda state: tool_gate(state, settings=settings))
    builder.add_node("human_approval", human_approval)
    builder.add_node("tool_execute", lambda state: tool_execute(state, settings=settings))
    builder.add_node("observe", lambda state: observe(state, settings=settings))
    builder.add_node("final_answer", lambda state: final_answer(state, logger=logger))

    builder.add_edge(START, "init_state")
    builder.add_edge("init_state", "skill_select")
    builder.add_edge("skill_select", "context_pack")
    builder.add_edge("context_pack", "budget_check")

    builder.add_conditional_edges(
        "budget_check", route_budget_check, {"ok": "call_model", "over_limit": "compact_context"}
    )
    builder.add_edge("compact_context", "context_pack")

    builder.add_conditional_edges(
        "call_model",
        route_model_result,
        {"tool_calls": "tool_gate", "final": "final_answer"},
    )

    builder.add_conditional_edges(
        "tool_gate",
        route_tool_gate,
        {"allowed": "tool_execute", "needs_approval": "human_approval", "denied": "call_model"},
    )
    builder.add_conditional_edges(
        "human_approval",
        route_human_approval,
        {"approved": "tool_execute", "rejected": "call_model"},
    )
    builder.add_conditional_edges(
        "tool_execute",
        route_tool_execute,
        {"success": "observe", "retryable_error": "observe", "fatal_error": "final_answer"},
    )
    builder.add_edge("observe", "context_pack")
    builder.add_edge("final_answer", END)

    return builder.compile(checkpointer=checkpointer)
