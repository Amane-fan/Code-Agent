from __future__ import annotations

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
    """One model response's token counts when the provider reports them."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class ModelCompletion:
    """Provider response text plus optional usage metadata."""

    text: str
    usage: TokenUsage | None = None


@dataclass(frozen=True)
class ModelCallUsage:
    """Audit record for one model provider call."""

    provider: str
    model: str
    purpose: str
    ok: bool
    usage: TokenUsage | None = None
    error: str = ""


@dataclass(frozen=True)
class ToolResult:
    """所有本地工具共享的返回格式，便于 Agent 统一处理成功、失败和元数据。"""

    name: str
    ok: bool
    output: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


EventKind = Literal["memory", "task", "summary", "action", "observation", "final_answer"]


@dataclass(frozen=True)
class AgentEvent:
    """ReAct 循环中的一条可审计历史事件。"""

    kind: EventKind
    content: str
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    result: ToolResult | None = None

    @property
    def tag(self) -> str:
        return f"<{self.kind}>{self.content}</{self.kind}>"

    def to_json_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": self.kind,
            "content": self.content,
            "tag": self.tag,
        }
        if self.tool is not None:
            data["tool"] = self.tool
        if self.args:
            data["args"] = self.args
        if self.result is not None:
            data["result"] = asdict(self.result)
        return data


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
