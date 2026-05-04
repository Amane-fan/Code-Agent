import operator
from typing import Annotated, Any, Literal

from typing_extensions import TypedDict


class ChatRecord(TypedDict, total=False):
    role: Literal["system", "user", "assistant", "tool", "developer"]
    content: str
    name: str | None
    tool_call_id: str | None
    metadata: dict[str, Any]


class AgentState(TypedDict, total=False):
    run_id: str
    thread_id: str
    workdir: str
    user_input: str

    messages: Annotated[list[ChatRecord], operator.add]
    context_messages: list[dict[str, Any]]
    context_summary: str
    packed_context: str
    selected_skills: list[str]
    skill_context: str
    skill_reason: str

    estimated_tokens: int
    token_budget: int
    budget_status: Literal["ok", "over_limit"]
    compact_attempts: int

    llm_calls: int
    model_response: dict[str, Any]
    model_route: Literal["tool_calls", "final"]
    force_final: bool

    pending_tool_calls: list[dict[str, Any]]
    approved_tool_calls: list[dict[str, Any]]
    denied_tool_calls: list[dict[str, Any]]
    tool_gate_route: Literal["allowed", "needs_approval", "denied"]
    approval_request: dict[str, Any]
    approval_result: Literal["approved", "rejected", "none"]
    tool_results: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    tool_error: dict[str, Any]
    tool_execute_status: Literal["success", "retryable_error", "fatal_error"]

    changed_files: Annotated[list[str], operator.add]
    commands_run: Annotated[list[str], operator.add]

    final_answer: str
