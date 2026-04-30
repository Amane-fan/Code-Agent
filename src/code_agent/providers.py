from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from importlib.resources import files
from typing import Protocol

from code_agent.config import configured_model, configured_value
from code_agent.models import WorkspaceContext


SYSTEM_INSTRUCTIONS = files("code_agent.prompts").joinpath("system.md").read_text(encoding="utf-8")

DEFAULT_RESPONSES_API_URL = "https://api.openai.com/v1/responses"


class ModelProvider(Protocol):
    """模型提供方协议，后续接 Anthropic、本地模型或代理服务都实现这个接口。"""

    @property
    def name(self) -> str:
        ...

    def complete(self, prompt: str, context: WorkspaceContext, *, model: str) -> str:
        ...


@dataclass(frozen=True)
class OfflineProvider:
    """不调用远端模型的本地模式，用于演示、测试和无 API key 环境。"""

    name: str = "offline"

    def complete(self, prompt: str, context: WorkspaceContext, *, model: str) -> str:
        return (
            "<think>离线模式不会调用远端模型或主动选择工具。</think>\n"
            "<final_answer>Offline mode received the task and produced no tool actions.</final_answer>"
        )


@dataclass(frozen=True)
class OpenAIResponsesProvider:
    """通过 OpenAI 兼容的 Responses API 生成 ReAct 下一步输出。"""

    name: str = "openai"

    def complete(self, prompt: str, context: WorkspaceContext, *, model: str) -> str:
        selected_model = configured_model() or model
        api_key = configured_value("OPENAI_API_KEY", "DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY or DASHSCOPE_API_KEY is required in Code-Agent .env "
                "or process environment"
            )

        # Responses API 使用 instructions 承载系统约束，input 承载 ReAct 历史和 workspace 边界。
        payload = {
            "model": selected_model,
            "instructions": SYSTEM_INSTRUCTIONS,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                f"User task:\n{prompt}\n\n"
                                f"Workspace context:\n{context.render(80_000)}"
                            ),
                        }
                    ],
                }
            ],
        }
        request = urllib.request.Request(
            _responses_api_url(),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI request failed: HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI request failed: {exc}") from exc

        return _extract_response_text(json.loads(body))


def make_provider(name: str) -> ModelProvider:
    """根据 CLI 配置创建模型提供方实例。"""

    normalized = name.lower().strip()
    if normalized == "offline":
        return OfflineProvider()
    if normalized == "openai":
        return OpenAIResponsesProvider()
    raise ValueError(f"unknown provider: {name}")


def _responses_api_url() -> str:
    """根据 Code-Agent 配置或当前环境中的 base_url 推导 Responses API 地址。"""

    explicit_url = configured_value("OPENAI_RESPONSES_URL", "DASHSCOPE_RESPONSES_URL")
    if explicit_url:
        return explicit_url

    base_url = configured_value("OPENAI_BASE_URL", "DASHSCOPE_BASE_URL")
    if base_url:
        return f"{base_url.rstrip('/')}/responses"
    return DEFAULT_RESPONSES_API_URL


def _extract_response_text(payload: dict[str, object]) -> str:
    """兼容 Responses API 的 output_text 快捷字段和结构化 output 列表。"""

    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text:
        return output_text

    chunks: list[str] = []
    output = payload.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    if chunks:
        return "\n".join(chunks)
    return json.dumps(payload, indent=2)
