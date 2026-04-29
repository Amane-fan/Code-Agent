from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


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
class ToolResult:
    """所有本地工具共享的返回格式，便于 Agent 统一处理成功、失败和元数据。"""

    name: str
    ok: bool
    output: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRun:
    """一次 Agent 执行的完整记录，可直接序列化为会话日志。"""

    prompt: str
    provider: str
    model: str
    response_text: str
    patch: str | None
    applied: bool
    context_files: list[str]
    test_result: ToolResult | None = None
    session_path: Path | None = None

    def to_json_dict(self) -> dict[str, Any]:
        # dataclass 默认会保留 Path 对象，这里转换成 JSON 更友好的字符串。
        data = asdict(self)
        if self.session_path is not None:
            data["session_path"] = str(self.session_path)
        if self.test_result is not None:
            data["test_result"] = asdict(self.test_result)
        return data
