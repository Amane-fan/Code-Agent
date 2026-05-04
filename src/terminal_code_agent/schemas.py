import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError


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


def fallback_answer(answer: str) -> str:
    """生成兜底最终回答文本。"""

    return answer


def parse_approval_resume(value: Any) -> ApprovalResume:
    """把 interrupt 恢复值解析为审批结果。"""

    if isinstance(value, ApprovalResume):
        return value
    if isinstance(value, str):
        try:
            return ApprovalResume.model_validate(json.loads(value))
        except (json.JSONDecodeError, ValidationError):
            decision: Literal["approved", "rejected"] = (
                "approved" if value.lower() in {"y", "yes", "approved"} else "rejected"
            )
            return ApprovalResume(decision=decision)
    return ApprovalResume.model_validate(value)
