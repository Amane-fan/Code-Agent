import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


class FinalAnswer(BaseModel):
    """模型最终回答，必须能被解析为裸 JSON 对象。"""

    type: Literal["final"] = "final"
    answer: str = Field(description="面向用户的最终回答")
    summary: str = Field(default="", description="本轮 agent 做了什么")
    changed_files: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    risks_or_notes: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class ToolResult(BaseModel):
    """所有工具统一返回结构，序列化后作为 ToolMessage 内容。"""

    ok: bool
    tool: str
    data: dict[str, Any] = Field(default_factory=dict)
    error_type: Literal["retryable_error", "fatal_error"] | None = None
    message: str = ""
    hint: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PendingToolCall(BaseModel):
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)


class SkillSelection(BaseModel):
    selected_skills: list[str] = Field(default_factory=list)
    reason: str = ""


class ApprovalRequest(BaseModel):
    type: Literal["tool_approval"] = "tool_approval"
    question: str
    tool_calls: list[PendingToolCall]
    risk: str


class ApprovalResume(BaseModel):
    decision: Literal["approved", "rejected"]
    edited_tool_calls: list[PendingToolCall] | None = None
    comment: str = ""


def parse_final_answer(content: str) -> FinalAnswer:
    """解析并校验最终 JSON；失败时抛出 ValidationError 或 JSONDecodeError。"""

    return FinalAnswer.model_validate(json.loads(content))


def fallback_final(
    answer: str,
    *,
    summary: str = "",
    changed_files: list[str] | None = None,
    commands_run: list[str] | None = None,
    risks_or_notes: list[str] | None = None,
    next_steps: list[str] | None = None,
) -> dict[str, Any]:
    """生成兜底最终回答，确保图总能产出合法 JSON。"""

    return FinalAnswer(
        answer=answer,
        summary=summary,
        changed_files=changed_files or [],
        commands_run=commands_run or [],
        risks_or_notes=risks_or_notes or [],
        next_steps=next_steps or [],
    ).model_dump()


def parse_approval_resume(value: Any) -> ApprovalResume:
    """把 interrupt 恢复值解析为审批结果。"""

    if isinstance(value, ApprovalResume):
        return value
    if isinstance(value, str):
        try:
            return ApprovalResume.model_validate(json.loads(value))
        except (json.JSONDecodeError, ValidationError):
            decision = "approved" if value.lower() in {"y", "yes", "approved"} else "rejected"
            return ApprovalResume(decision=decision)
    return ApprovalResume.model_validate(value)
