from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from code_agent.env import get_env_file, get_repo_env, load_env_file
from code_agent.models import RepoContext


SYSTEM_INSTRUCTIONS = (
    "You are a cautious terminal coding agent.\n"
    "Use the repository context to propose the smallest correct change.\n"
    "When editing is needed, include exactly one fenced diff block with a "
    "git-apply-compatible unified diff.\n"
    "Do not include secrets. Prefer adding tests when behavior changes.\n"
    "End with a short verification plan."
)

DEFAULT_RESPONSES_API_URL = "https://api.openai.com/v1/responses"


class ModelProvider(Protocol):
    """模型提供方协议，后续接 Anthropic、本地模型或代理服务都实现这个接口。"""

    @property
    def name(self) -> str:
        ...

    def complete(self, prompt: str, context: RepoContext, *, model: str) -> str:
        ...


@dataclass(frozen=True)
class OfflineProvider:
    """不调用远端模型的本地模式，用于演示、测试和无 API key 环境。"""

    name: str = "offline"

    def complete(self, prompt: str, context: RepoContext, *, model: str) -> str:
        files = ", ".join(file.path for file in context.files) or "no readable files"
        return (
            "Offline planning mode\n\n"
            f"Task: {prompt}\n\n"
            "Relevant files inspected:\n"
            f"{files}\n\n"
            "Suggested next steps:\n"
            "1. Review the files above and identify the smallest behavior change.\n"
            "2. Ask the OpenAI provider to generate a unified diff, or write the patch manually.\n"
            "3. Run the detected test command before committing.\n\n"
            "No patch was generated because the offline provider does not call an LLM."
        )


@dataclass(frozen=True)
class OpenAIResponsesProvider:
    """通过 OpenAI 兼容的 Responses API 生成计划和补丁。"""

    name: str = "openai"

    def complete(self, prompt: str, context: RepoContext, *, model: str) -> str:
        # Provider 调用前再加载一次仓库 .env，覆盖直接使用 Provider 的场景。
        env_path = context.root / ".env"
        load_env_file(env_path, override=True)
        configured_model = get_env_file(env_path, "OPENAI_MODEL", "DASHSCOPE_MODEL")
        if not configured_model:
            raise RuntimeError("OPENAI_MODEL or DASHSCOPE_MODEL is required in .env")

        api_key = get_env_file(env_path, "OPENAI_API_KEY", "DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY or DASHSCOPE_API_KEY is required in .env")

        # Responses API 使用 instructions 承载系统约束，input 承载用户任务和仓库上下文。
        payload = {
            "model": configured_model,
            "instructions": SYSTEM_INSTRUCTIONS,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                f"User task:\n{prompt}\n\n"
                                f"Repository context:\n{context.render(80_000)}"
                            ),
                        }
                    ],
                }
            ],
        }
        request = urllib.request.Request(
            _responses_api_url(context.root),
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


def _responses_api_url(repo_root: Path | None = None) -> str:
    """根据仓库 .env 或当前环境中的 base_url 推导 Responses API 地址。"""

    explicit_url = get_repo_env(repo_root, "OPENAI_RESPONSES_URL", "DASHSCOPE_RESPONSES_URL")
    if explicit_url:
        return explicit_url

    base_url = get_repo_env(repo_root, "OPENAI_BASE_URL", "DASHSCOPE_BASE_URL")
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
