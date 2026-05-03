from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from code_agent.config import configured_model, configured_value
from code_agent.models import ModelCompletion, ModelToolCall, TokenUsage


CHAT_COMPLETIONS_SUFFIX = "/chat/completions"


class ModelProvider(Protocol):
    """模型提供方协议，后续接 Anthropic、本地模型或代理服务都实现这个接口。"""

    @property
    def name(self) -> str:
        ...

    def complete(
        self,
        messages: Sequence[BaseMessage],
        *,
        model: str,
        tools: Sequence[BaseTool] | None = None,
    ) -> ModelCompletion:
        ...


@dataclass(frozen=True)
class OfflineProvider:
    """不调用远端模型的本地模式，用于演示、测试和无 API key 环境。"""

    name: str = "offline"

    def complete(
        self,
        messages: Sequence[BaseMessage],
        *,
        model: str,
        tools: Sequence[BaseTool] | None = None,
    ) -> ModelCompletion:
        return ModelCompletion(
            text=json.dumps(
                {
                    "role": "assistant",
                    "type": "final_answer",
                    "content": "Offline mode received the task and produced no tool actions.",
                },
                ensure_ascii=False,
            )
        )


@dataclass(frozen=True)
class OpenAICompatibleChatProvider:
    """通过 LangChain 调用 OpenAI 兼容的 chat model，使用原生 tool-calling。"""

    name: str = "openai"

    def complete(
        self,
        messages: Sequence[BaseMessage],
        *,
        model: str,
        tools: Sequence[BaseTool] | None = None,
    ) -> ModelCompletion:
        selected_model = configured_model() or model
        api_key = configured_value("API_KEY", "OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "API_KEY or OPENAI_API_KEY is required in Code-Agent .env or process environment"
            )

        try:
            llm = _ReasoningContentChatOpenAI(
                model=selected_model,
                api_key=SecretStr(api_key),
                base_url=_langchain_base_url(),
                timeout=120,
                max_retries=0,
            )
            runnable = llm.bind_tools(list(tools)) if tools else llm
            message = runnable.invoke(list(messages))
        except Exception as exc:
            raise RuntimeError(f"LangChain model request failed: {exc}") from exc

        return ModelCompletion(
            text=_extract_langchain_message_text(message),
            usage=_extract_langchain_token_usage(message),
            tool_calls=_extract_langchain_tool_calls(message),
            reasoning_content=_extract_langchain_reasoning_content(message),
        )


class _ReasoningContentChatOpenAI(ChatOpenAI):
    """保留 OpenAI 兼容 thinking 模式要求回灌的 reasoning_content。"""

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
            reasoning_content = _extract_langchain_reasoning_content(source_message)
            if reasoning_content:
                # LangChain 当前不会自动序列化这个兼容字段，这里补回给下游 API。
                payload_message["reasoning_content"] = reasoning_content
        return payload

    def _create_chat_result(
        self,
        response: Any,
        generation_info: dict[str, Any] | None = None,
    ) -> Any:
        raw_response = _openai_response_to_mapping(response)
        chat_result = super()._create_chat_result(response, generation_info)
        choices = raw_response.get("choices") if isinstance(raw_response, dict) else None
        if not isinstance(choices, list):
            return chat_result

        for generation, choice in zip(chat_result.generations, choices, strict=False):
            message = _object_value(choice, "message")
            reasoning_content = _extract_reasoning_content_from_value(message)
            if reasoning_content and isinstance(generation.message, AIMessage):
                generation.message.additional_kwargs["reasoning_content"] = reasoning_content
        return chat_result


def _openai_response_to_mapping(response: object) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    model_dump = getattr(response, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(exclude={"choices": {"__all__": {"message": {"parsed"}}}})
        if isinstance(dumped, dict):
            return dumped
    return {}


def make_provider(name: str, *, system_instructions: str | None = None) -> ModelProvider:
    """根据 CLI 配置创建模型提供方实例。system_instructions 参数保留兼容。"""

    _ = system_instructions
    normalized = name.lower().strip()
    if normalized == "offline":
        return OfflineProvider()
    if normalized == "openai":
        return OpenAICompatibleChatProvider()
    raise ValueError(f"unknown provider: {name}")


def _langchain_base_url() -> str | None:
    """读取 LangChain ChatOpenAI 可接受的 OpenAI-compatible base URL。"""

    base_url = configured_value("BASE_URL", "OPENAI_BASE_URL")
    if not base_url:
        return None

    normalized = base_url.rstrip("/")
    if normalized.endswith(CHAT_COMPLETIONS_SUFFIX):
        return normalized[: -len(CHAT_COMPLETIONS_SUFFIX)].rstrip("/")
    return normalized


def _extract_langchain_message_text(message: object) -> str:
    """从 LangChain message content 或文本 content block 中提取纯文本。"""

    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content

    chunks: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                chunks.append(block)
                continue
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    chunks.append(text)
                continue
            text = getattr(block, "text", None)
            if isinstance(text, str):
                chunks.append(text)
    if chunks:
        return "\n".join(chunks)

    return str(content)


def _extract_langchain_tool_calls(message: object) -> list[ModelToolCall]:
    raw_calls = _object_value(message, "tool_calls")
    if not isinstance(raw_calls, list):
        return []

    calls: list[ModelToolCall] = []
    for index, raw_call in enumerate(raw_calls, start=1):
        name = _object_value(raw_call, "name")
        raw_args = _object_value(raw_call, "args")
        raw_id = _object_value(raw_call, "id")
        if not isinstance(name, str) or not name:
            continue
        args = _normalize_tool_call_args(raw_args)
        call_id = raw_id if isinstance(raw_id, str) and raw_id else f"call_{index}"
        calls.append(ModelToolCall(id=call_id, name=name, args=args))
    return calls


def _extract_langchain_reasoning_content(message: object) -> str:
    reasoning_content = _object_value(message, "reasoning_content")
    if isinstance(reasoning_content, str):
        return reasoning_content

    additional_kwargs = _object_value(message, "additional_kwargs")
    reasoning_content = _extract_reasoning_content_from_value(additional_kwargs)
    if reasoning_content:
        return reasoning_content

    response_metadata = _object_value(message, "response_metadata")
    reasoning_content = _extract_reasoning_content_from_value(response_metadata)
    if reasoning_content:
        return reasoning_content

    content = _object_value(message, "content")
    if isinstance(content, list):
        reasoning_content = _extract_reasoning_content_from_value(content)
        if reasoning_content:
            return reasoning_content
    return ""


def _extract_reasoning_content_from_value(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        direct = value.get("reasoning_content")
        if isinstance(direct, str):
            return direct

        reasoning = value.get("reasoning")
        if isinstance(reasoning, str):
            return reasoning
        if isinstance(reasoning, dict):
            nested = _reasoning_text_from_mapping(reasoning)
            if nested:
                return nested

        if _is_reasoning_block(value):
            block_text = _reasoning_text_from_mapping(value)
            if block_text:
                return block_text
        return ""
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and _is_reasoning_block(item):
                block_text = _reasoning_text_from_mapping(item)
                if block_text:
                    return block_text
    return ""


def _reasoning_text_from_mapping(value: dict[str, Any]) -> str:
    for key in ("reasoning_content", "content", "text"):
        candidate = value.get(key)
        if isinstance(candidate, str):
            return candidate
    return ""


def _is_reasoning_block(value: dict[str, Any]) -> bool:
    block_type = value.get("type")
    return isinstance(block_type, str) and "reason" in block_type.lower()


def _normalize_tool_call_args(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _extract_langchain_token_usage(message: object) -> TokenUsage | None:
    """从 LangChain AIMessage 常见元数据格式中提取 token usage。"""

    usage_metadata = _object_value(message, "usage_metadata")
    usage = _usage_from_mapping_or_object(
        usage_metadata,
        prompt_keys=("input_tokens", "prompt_tokens"),
        completion_keys=("output_tokens", "completion_tokens"),
        total_keys=("total_tokens",),
    )
    if usage is not None:
        return usage

    response_metadata = _object_value(message, "response_metadata")
    token_usage = _object_value(response_metadata, "token_usage")
    return _usage_from_mapping_or_object(
        token_usage,
        prompt_keys=("prompt_tokens", "input_tokens"),
        completion_keys=("completion_tokens", "output_tokens"),
        total_keys=("total_tokens",),
    )


def _usage_from_mapping_or_object(
    value: object,
    *,
    prompt_keys: tuple[str, ...],
    completion_keys: tuple[str, ...],
    total_keys: tuple[str, ...],
) -> TokenUsage | None:
    if value is None:
        return None
    prompt_tokens = _first_int(value, prompt_keys)
    completion_tokens = _first_int(value, completion_keys)
    total_tokens = _first_int(value, total_keys)
    if prompt_tokens is None and completion_tokens is None and total_tokens is None:
        return None
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def _first_int(value: object, keys: tuple[str, ...]) -> int | None:
    for key in keys:
        raw = _object_value(value, key)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int):
            return raw
    return None


def _object_value(value: object, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)
