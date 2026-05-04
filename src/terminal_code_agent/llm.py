from typing import Any

from langchain.chat_models import init_chat_model

from terminal_code_agent.config import Settings


def build_chat_model(settings: Settings):
    """根据 .env 配置初始化 ChatModel。"""

    kwargs: dict[str, Any] = {
        "temperature": settings.model_temperature,
        "timeout": settings.model_timeout_seconds,
        "max_tokens": settings.model_max_tokens,
    }
    if settings.model_base_url:
        kwargs["base_url"] = settings.model_base_url
    return init_chat_model(settings.model_name, **kwargs)
