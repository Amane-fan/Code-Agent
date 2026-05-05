from typing import Any

from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from terminal_code_agent.config import Settings


def _response_to_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        return response.model_dump(exclude={"choices": {"__all__": {"message": {"parsed"}}}})
    return {}


class DeepSeekThinkingChatOpenAI(ChatOpenAI):
    """保留 DeepSeek thinking + tool-call 流程需要回传的 reasoning_content。"""

    def _create_chat_result(
        self,
        response: Any,
        generation_info: dict[str, Any] | None = None,
    ):
        response_dict = _response_to_dict(response)
        result = super()._create_chat_result(response, generation_info=generation_info)
        for generation, choice in zip(
            result.generations, response_dict.get("choices") or [], strict=False
        ):
            message = generation.message
            if not isinstance(message, AIMessage):
                continue
            raw_message = choice.get("message") or {}
            reasoning_content = raw_message.get("reasoning_content")
            if reasoning_content is not None:
                message.additional_kwargs["reasoning_content"] = reasoning_content
        return result

    def _get_request_payload(
        self,
        input_: Any,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        messages = self._convert_input(input_).to_messages()
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        payload_messages = payload.get("messages")
        if not isinstance(payload_messages, list):
            return payload
        for source_message, payload_message in zip(messages, payload_messages, strict=False):
            if not isinstance(source_message, AIMessage) or not isinstance(payload_message, dict):
                continue
            reasoning_content = source_message.additional_kwargs.get("reasoning_content")
            if reasoning_content is not None:
                payload_message["reasoning_content"] = reasoning_content
        return payload


def _normalize_openai_model_name(model_name: str) -> str:
    """支持旧的 openai: 前缀，同时默认使用 ChatOpenAI 的裸模型名。"""

    if model_name.startswith("openai:"):
        return model_name.split(":", 1)[1]
    if ":" in model_name:
        raise ValueError(
            "MODEL_NAME 使用 ChatOpenAI 初始化，请配置为裸模型名，"
            "例如 gpt-4.1-mini 或 deepseek-chat。"
        )
    return model_name


def build_chat_model(settings: Settings):
    """根据 .env 配置初始化 ChatModel。"""

    kwargs: dict[str, Any] = {
        "model": _normalize_openai_model_name(settings.model_name),
        "temperature": settings.model_temperature,
        "timeout": settings.model_timeout_seconds,
        "max_tokens": settings.model_max_tokens,
    }
    if settings.model_base_url:
        kwargs["base_url"] = settings.model_base_url
    return DeepSeekThinkingChatOpenAI(**kwargs)
