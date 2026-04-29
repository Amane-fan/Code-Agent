from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_MODEL = "gpt-4.1-mini"


@dataclass(frozen=True)
class AgentConfig:
    """单次 Agent 运行的配置入口。

    配置对象保持不可变，避免一次运行过程中仓库路径、模型或上下文上限被意外改动。
    """

    repo_path: Path = field(default_factory=Path.cwd)
    provider: str = "offline"
    model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", DEFAULT_MODEL))
    max_files: int = 12
    max_file_bytes: int = 24_000
    max_context_chars: int = 80_000
    session_dir_name: str = ".code-agent"

    @property
    def repo_root(self) -> Path:
        # 所有文件操作都基于规范化后的仓库根目录，后续安全校验依赖这个绝对路径。
        return self.repo_path.expanduser().resolve()

    @property
    def session_dir(self) -> Path:
        # 会话日志默认放在仓库内的本地目录，并由 .gitignore 排除。
        return self.repo_root / self.session_dir_name
