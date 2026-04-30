from __future__ import annotations

import re
from pathlib import Path


EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "target",
    ".next",
    ".turbo",
    ".code-agent",
    "coverage",
}

# 这些文件名通常包含凭据或本地工具状态，不能进入模型上下文。
SENSITIVE_NAMES = {
    ".codex",
    ".env",
    ".env.local",
    ".env.production",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "id_rsa",
    "id_ed25519",
    "credentials",
    "credentials.json",
}

# 二进制文件不适合直接发送给模型，也容易造成乱码或上下文浪费。
BINARY_EXTENSIONS = {
    ".7z",
    ".avif",
    ".bin",
    ".bmp",
    ".class",
    ".dll",
    ".dmg",
    ".exe",
    ".gif",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".lockb",
    ".mov",
    ".mp3",
    ".mp4",
    ".o",
    ".pdf",
    ".png",
    ".pyc",
    ".pyo",
    ".so",
    ".tar",
    ".webp",
    ".zip",
}

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?([A-Za-z0-9_\-./+=]{16,})"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
]


def is_sensitive_path(path: Path) -> bool:
    """判断路径是否应该从文件工具和上下文收集中排除。"""

    parts = set(path.parts)
    if any(part in EXCLUDED_DIRS for part in parts):
        return True
    name = path.name.lower()
    if name in SENSITIVE_NAMES:
        return True
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return True
    return False


def ensure_within_workspace(workspace_root: Path, candidate: Path) -> Path:
    """解析用户输入路径，并确保它没有逃逸出 workspace 根目录。"""

    resolved = (
        (workspace_root / candidate).resolve()
        if not candidate.is_absolute()
        else candidate.resolve()
    )
    resolved.relative_to(workspace_root.resolve())
    return resolved


def ensure_within_repo(repo_root: Path, candidate: Path) -> Path:
    """向后兼容旧名称；新代码应使用 ensure_within_workspace。"""

    return ensure_within_workspace(repo_root, candidate)


def redact_secrets(text: str) -> str:
    """对工具输出和上下文文本做最后一层密钥脱敏。"""

    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(_redact_match, redacted)
    return redacted


def _redact_match(match: re.Match[str]) -> str:
    if match.lastindex is None:
        return "[REDACTED]"
    secret = match.group(match.lastindex)
    return match.group(0).replace(secret, "[REDACTED]")

