from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from code_agent.config import configured_model, configured_value
from code_agent.models import ModelCompletion, TokenUsage, WorkspaceContext
from code_agent.prompting import BASE_SYSTEM_INSTRUCTIONS


SYSTEM_INSTRUCTIONS = BASE_SYSTEM_INSTRUCTIONS

CHAT_COMPLETIONS_SUFFIX = "/chat/completions"


class ModelProvider(Protocol):
    """模型提供方协议，后续接 Anthropic、本地模型或代理服务都实现这个接口。"""

    @property
    def name(self) -> str:
        ...

    def complete(self, prompt: str, context: WorkspaceContext, *, model: str) -> str | ModelCompletion:
        ...


@dataclass(frozen=True)
class OfflineProvider:
    """不调用远端模型的本地模式，用于演示、测试和无 API key 环境。"""

    name: str = "offline"

    def complete(self, prompt: str, context: WorkspaceContext, *, model: str) -> ModelCompletion:
        return ModelCompletion(
            text=(
                "<summary>离线模式不会调用远端模型或主动选择工具。</summary>\n"
                "<final_answer>Offline mode received the task and produced no tool actions.</final_answer>"
            )
        )


@dataclass(frozen=True)
class OpenAICompatibleChatProvider:
    """通过 LangChain 调用 OpenAI 兼容的 chat model，生成 ReAct 下一步输出。"""

    name: str = "openai"
    system_instructions: str = BASE_SYSTEM_INSTRUCTIONS

    def complete(self, prompt: str, context: WorkspaceContext, *, model: str) -> ModelCompletion:
        selected_model = configured_model() or model
        api_key = configured_value("API_KEY", "OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "API_KEY or OPENAI_API_KEY is required in Code-Agent .env or process environment"
            )

        try:
            llm = ChatOpenAI(
                model=selected_model,
                api_key=SecretStr(api_key),
                base_url=_langchain_base_url(),
                timeout=120,
                max_retries=0,
            )
            message = llm.invoke([("system", self.system_instructions), ("human", prompt)])
        except Exception as exc:
            raise RuntimeError(f"LangChain model request failed: {exc}") from exc

        return ModelCompletion(
            text=_extract_langchain_message_text(message),
            usage=_extract_langchain_token_usage(message),
        )


def make_provider(name: str, *, system_instructions: str | None = None) -> ModelProvider:
    """根据 CLI 配置创建模型提供方实例。"""

    normalized = name.lower().strip()
    if normalized == "offline":
        return OfflineProvider()
    if normalized == "openai":
        return OpenAICompatibleChatProvider(
            system_instructions=system_instructions or BASE_SYSTEM_INSTRUCTIONS
        )
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
