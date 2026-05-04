from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，统一从 .env 和环境变量读取。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    model_name: str = "openai:gpt-4.1-mini"
    model_temperature: float = 0
    model_max_tokens: int = 4096
    model_timeout_seconds: int = 120
    model_context_window: int = 128000
    model_base_url: str | None = None

    token_budget_ratio: float = 0.85
    max_tool_repair_attempts: int = 3
    max_compact_attempts: int = 2
    max_context_chars_per_tool_result: int = 12000
    shell_timeout_seconds: int = 60
    require_approval_for_write: bool = True

    log_level: str = "INFO"
    log_dir: Path = Path(".agent/logs")
    skills_dir: Path = Path("skills")
    checkpoint_db: Path = Path(".agent/checkpoints.sqlite")


def load_settings(env_file: str | Path = ".env") -> Settings:
    """按 CLI 指定的 env 文件加载配置。"""

    # 先加载到进程环境，确保 LangChain provider SDK 能读取 API key。
    load_dotenv(env_file, override=False)
    return Settings(_env_file=env_file)  # type: ignore[call-arg]
