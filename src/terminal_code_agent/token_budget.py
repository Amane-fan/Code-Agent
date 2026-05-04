import json
from typing import Any


def compute_token_budget(context_window: int, max_tokens: int, ratio: float) -> int:
    """根据模型上下文窗口计算可用输入预算。"""

    return int((context_window - max_tokens) * ratio)


def estimate_tokens(text: str, model_name: str | None = None) -> int:
    """估算 token 数；中文场景使用更保守的 fallback。"""

    try:
        import tiktoken

        model_key = (model_name or "").split(":", 1)[-1]
        try:
            encoding = tiktoken.encoding_for_model(model_key)
        except Exception:
            encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        return max(len(text) // 2, len(text.encode("utf-8")) // 4)


def pack_for_estimation(value: Any) -> str:
    """把 state 片段稳定序列化，供预算估算使用。"""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
