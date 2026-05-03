from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class ContextFile:
    """发送给模型的单个上下文文件片段。"""

    path: str
    score: int
    language: str
    content: str


@dataclass(frozen=True)
class WorkspaceContext:
    """模型调用前汇总出的 workspace 上下文。"""

    root: Path
    prompt: str
    git_status: str
    files: list[ContextFile]

    def render(self, max_chars: int) -> str:
        # 统一在这里渲染 prompt 上下文，方便后续替换为压缩摘要或结构化消息。
        sections = [
            f"Workspace: {self.root}",
            "Git status:",
            self.git_status.strip() or "clean or unavailable",
            "Relevant files:",
        ]
        for file in self.files:
            sections.append(f"\n--- {file.path} ({file.language}, score={file.score}) ---")
            sections.append(file.content)
        rendered = "\n".join(sections)
        if len(rendered) <= max_chars:
            return rendered
        return rendered[:max_chars] + "\n\n[context truncated]"


RepoContext = WorkspaceContext


@dataclass(frozen=True)
class TokenUsage:
    """单次模型响应的 token 数量，由 provider 上报时填充。"""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class ModelCompletion:
    """Provider 响应内容，附带工具调用和 token usage 元数据。"""

    text: str
    usage: TokenUsage | None = None
    tool_calls: list["ModelToolCall"] = field(default_factory=list)
    reasoning_content: str = ""


@dataclass(frozen=True)
class ModelToolCall:
    """模型通过原生 tool-calling 接口请求的一次工具调用。"""

    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelCallUsage:
    """一次模型提供方调用的审计记录。"""

    provider: str
    model: str
    purpose: str
    ok: bool
    usage: TokenUsage | None = None
    error: str = ""
    system_instructions: str = ""


@dataclass(frozen=True)
class ToolResult:
    """所有本地工具共享的返回格式，便于 Agent 统一处理成功、失败和元数据。"""

    name: str
    ok: bool
    output: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


EventRole = Literal["system", "user", "assistant", "tool"]
EventType = Literal["memory", "task", "summary", "tool_call", "tool_result", "final_answer"]


@dataclass(frozen=True)
class AgentEvent:
    """ReAct 循环中的一条 JSON 可审计历史事件。"""

    role: EventRole
    type: EventType
    content: str = ""
    tool: str | None = None
    call_id: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    result: ToolResult | None = None
    reasoning_content: str = ""

    @property
    def kind(self) -> EventType:
        """兼容旧调用点；新代码应使用 type。"""

        return self.type

    def to_json_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "role": self.role,
            "type": self.type,
            "content": self.content,
        }
        if self.tool is not None:
            data["tool"] = self.tool
        if self.call_id is not None:
            data["call_id"] = self.call_id
        if self.args:
            data["args"] = self.args
        if self.result is not None:
            data["result"] = self.result.to_json_dict()
        return data

    def to_json_line(self) -> str:
        return json.dumps(self.to_json_dict(), ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class AgentRun:
    """一次 Agent 执行的完整记录，可直接序列化为会话日志。"""

    prompt: str
    provider: str
    model: str
    final_answer: str
    response_text: str
    history: list[AgentEvent]
    iterations: int
    model_calls: list[ModelCallUsage] = field(default_factory=list)
    context_files: list[str] = field(default_factory=list)
    session_path: Path | None = None

    def to_json_dict(self) -> dict[str, Any]:
        # dataclass 默认会保留 Path 对象，这里转换成 JSON 更友好的字符串。
        data = asdict(self)
        data["history"] = [event.to_json_dict() for event in self.history]
        if self.session_path is not None:
            data["session_path"] = str(self.session_path)
        return data
