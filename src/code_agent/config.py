from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from code_agent.env import get_env, get_env_file, load_env_file


DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_PROVIDER = "openai"
CODE_AGENT_ENV_FILE_ENV_VAR = "CODE_AGENT_ENV_FILE"
CODE_AGENT_PROJECT_ROOT = Path(__file__).resolve().parents[2]
CODE_AGENT_ENV_PATH = CODE_AGENT_PROJECT_ROOT / ".env"


def code_agent_env_path() -> Path:
    """返回 Code-Agent 自身的配置文件路径。"""

    override = os.getenv(CODE_AGENT_ENV_FILE_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()
    return CODE_AGENT_ENV_PATH


def configured_value(*names: str, default: str = "") -> str:
    """从 Code-Agent 配置文件读取值，缺失时回退到进程环境变量。"""

    value = get_env_file(code_agent_env_path(), *names)
    if value:
        return value
    return get_env(*names, default=default)


def configured_model() -> str:
    """读取模型配置，不读取目标 workspace 的 .env。"""

    return configured_value("MODEL", "OPENAI_MODEL", default=DEFAULT_MODEL)


@dataclass(frozen=True)
class AgentConfig:
    """单次 Agent 运行的配置入口。

    配置对象保持不可变，避免一次运行过程中 workspace 路径、模型或上下文上限被意外改动。
    """

    workspace_path: Path = field(default_factory=Path.cwd)
    provider: str = DEFAULT_PROVIDER
    model: str = field(default=DEFAULT_MODEL, init=False)
    max_files: int = 12
    max_file_bytes: int = 24_000
    max_context_chars: int = 80_000
    max_conversation_chars: int = 60_000
    recent_turns_to_keep: int = 2
    max_iterations: int = 20
    session_dir_name: str = ".code-agent"
    session_root: Path | None = None
    skills_path: Path | None = None

    def __post_init__(self) -> None:
        # 模型调用配置只来自 Code-Agent 自身配置，目标 workspace 的 .env 不参与模型配置。
        load_env_file(code_agent_env_path(), override=True)
        object.__setattr__(self, "model", configured_model())

    @property
    def workspace_root(self) -> Path:
        # 所有 workspace 文件操作都基于规范化后的绝对路径，后续安全校验依赖它。
        return self.workspace_path.expanduser().resolve()

    @property
    def repo_root(self) -> Path:
        """向后兼容旧内部调用；新代码应使用 workspace_root。"""

        return self.workspace_root

    @property
    def session_dir(self) -> Path:
        # 会话日志属于 Code-Agent 自身状态，不写入目标 workspace。
        if self.session_root is not None:
            return self.session_root.expanduser().resolve()
        return CODE_AGENT_PROJECT_ROOT / self.session_dir_name

    @property
    def skills_root(self) -> Path:
        if self.skills_path is not None:
            return self.skills_path.expanduser().resolve()
        return CODE_AGENT_PROJECT_ROOT / "skills"
