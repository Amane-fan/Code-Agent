from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from code_agent.env import get_repo_env, load_env_file


DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_PROVIDER = "openai"


def configured_model(repo_root: Path | None = None) -> str:
    """读取模型配置，仓库 .env 优先于当前进程环境变量。"""

    return get_repo_env(repo_root, "OPENAI_MODEL", "DASHSCOPE_MODEL", default=DEFAULT_MODEL)


@dataclass(frozen=True)
class AgentConfig:
    """单次 Agent 运行的配置入口。

    配置对象保持不可变，避免一次运行过程中仓库路径、模型或上下文上限被意外改动。
    """

    repo_path: Path = field(default_factory=Path.cwd)
    provider: str = DEFAULT_PROVIDER
    model: str = field(default=DEFAULT_MODEL, init=False)
    max_files: int = 12
    max_file_bytes: int = 24_000
    max_context_chars: int = 80_000
    session_dir_name: str = ".code-agent"

    def __post_init__(self) -> None:
        # 模型调用配置以仓库 .env 为准，避免 CLI 或外部环境意外覆盖本项目配置。
        load_env_file(self.repo_root / ".env", override=True)
        object.__setattr__(self, "model", configured_model(self.repo_root))

    @property
    def repo_root(self) -> Path:
        # 所有文件操作都基于规范化后的仓库根目录，后续安全校验依赖这个绝对路径。
        return self.repo_path.expanduser().resolve()

    @property
    def session_dir(self) -> Path:
        # 会话日志默认放在仓库内的本地目录，并由 .gitignore 排除。
        return self.repo_root / self.session_dir_name
