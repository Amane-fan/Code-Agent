import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s]+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]


def truncate_text(text: str, max_chars: int = 4000) -> str:
    """截断长文本，避免日志中出现大段工具输出。"""

    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...[TRUNCATED {len(text) - max_chars} chars]"


def redact(value: Any, *, max_chars: int = 4000) -> Any:
    """递归脱敏日志数据，避免泄露密钥和完整 .env 内容。"""

    if isinstance(value, str):
        redacted = value
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return truncate_text(redacted, max_chars)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in {"content", "stdout", "stderr"} and ".env" in str(
                value.get("path", "")
            ):
                result[key] = "[REDACTED]"
            elif any(word in key.lower() for word in ("key", "token", "secret", "password")):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact(item, max_chars=max_chars)
        return result
    if isinstance(value, list):
        return [redact(item, max_chars=max_chars) for item in value]
    return value


class JsonlLogger:
    """简单 JSON Lines 日志器；节点调用它记录审计事件。"""

    def __init__(self, log_dir: Path, *, level: str = "INFO") -> None:
        self.log_dir = log_dir
        self.level = level
        self.session_id = uuid4().hex
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.path = self.log_dir / f"agent-{stamp}-{self.session_id[:8]}.jsonl"

    def event(
        self,
        event: str,
        *,
        run_id: str = "",
        thread_id: str = "",
        node: str = "",
        message: str = "",
        data: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "level": self.level,
            "session_id": self.session_id,
            "event": event,
            "run_id": run_id,
            "thread_id": thread_id,
            "node": node,
            "message": message,
            "data": redact(data or {}),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
