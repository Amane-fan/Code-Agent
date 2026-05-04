import fnmatch
import json
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from terminal_code_agent.schemas import ToolResult


class SecurityError(Exception):
    """安全策略拒绝。"""


IGNORED_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}

SENSITIVE_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    ".ssh/*",
    ".aws/credentials",
    ".gcloud/*",
    ".azure/*",
    ".npmrc",
    ".pypirc",
    ".netrc",
]

DANGEROUS_COMMAND_PATTERNS = [
    re.compile(r"(^|\s)sudo(\s|$)"),
    re.compile(r"(^|\s)su(\s|$)"),
    re.compile(r"rm\s+-[^&|;]*r[^&|;]*f\s+(/|~)(\s|$)"),
    re.compile(r":\(\)\s*\{\s*:\|:&\s*\};:"),
    re.compile(r"chmod\s+-R\s+777\s+/"),
    re.compile(r"chown\s+-R\s+"),
    re.compile(r"cat\s+~/.ssh/"),
    re.compile(r"cat\s+\.env(\s|$)"),
    re.compile(r"(curl|wget)\b.*\|\s*sh\b"),
]


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    """截断工具输出，返回截断后的文本和是否截断。"""

    if len(text) <= max_chars:
        return text, False
    return f"{text[:max_chars]}...[TRUNCATED {len(text) - max_chars} chars]", True


def result_json(result: ToolResult) -> str:
    return result.model_dump_json()


def ok_result(
    tool: str,
    data: dict[str, Any] | None = None,
    *,
    message: str = "",
    metadata: dict[str, Any] | None = None,
) -> str:
    return result_json(
        ToolResult(ok=True, tool=tool, data=data or {}, message=message, metadata=metadata or {})
    )


def error_result(
    tool: str,
    error_type: str,
    message: str,
    *,
    hint: str = "",
    metadata: dict[str, Any] | None = None,
) -> str:
    return result_json(
        ToolResult(
            ok=False,
            tool=tool,
            error_type=error_type,  # type: ignore[arg-type]
            message=message,
            hint=hint,
            metadata=metadata or {},
        )
    )


def resolve_in_root(root: Path, user_path: str) -> Path:
    """把用户传入路径解析到 root 内部，禁止路径逃逸。"""

    base = root.resolve()
    target = (base / user_path).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise SecurityError(f"路径逃逸出允许目录: {user_path}") from exc
    return target


def relative_to_root(root: Path, target: Path) -> str:
    return target.resolve().relative_to(root.resolve()).as_posix() or "."


def is_hidden_relative(rel_path: str) -> bool:
    return any(part.startswith(".") for part in Path(rel_path).parts if part not in {"."})


def is_ignored_dir(path: Path) -> bool:
    return path.name in IGNORED_DIRS


def is_sensitive_relative(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    name = Path(normalized).name
    for pattern in SENSITIVE_PATTERNS:
        if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(name, pattern):
            return True
    return False


def ensure_not_sensitive(root: Path, target: Path) -> None:
    rel_path = relative_to_root(root, target)
    if is_sensitive_relative(rel_path):
        raise SecurityError(f"安全策略拒绝访问敏感路径: {rel_path}")


def ensure_safe_path(root: Path, user_path: str, *, check_sensitive: bool = True) -> Path:
    target = resolve_in_root(root, user_path)
    if check_sensitive:
        ensure_not_sensitive(root, target)
    return target


def is_binary_file(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:2048]
    except OSError:
        return False
    return b"\0" in chunk


def iter_files(root: Path, start: Path, *, include_hidden: bool = False) -> Iterable[Path]:
    """遍历工作目录内文件，统一跳过隐藏目录和大缓存目录。"""

    for path in sorted(start.rglob("*")):
        rel_path = relative_to_root(root, path)
        if any(part in IGNORED_DIRS for part in Path(rel_path).parts):
            continue
        if not include_hidden and is_hidden_relative(rel_path):
            continue
        yield path


def read_text_file(path: Path) -> str:
    if is_binary_file(path):
        raise ValueError("二进制文件不能作为文本读取")
    return path.read_text(encoding="utf-8", errors="replace")


def with_line_numbers(content: str, *, start_line: int = 1) -> str:
    return "\n".join(
        f"{line_number}: {line}"
        for line_number, line in enumerate(content.splitlines(), start_line)
    )


def extract_patch_paths(patch: str) -> list[str]:
    """从 unified diff 中提取被修改路径，用于安全预检。"""

    paths: list[str] = []
    for line in patch.splitlines():
        if line.startswith(("--- ", "+++ ")):
            value = line[4:].strip().split("\t", 1)[0]
            if value == "/dev/null":
                continue
            if value.startswith(("a/", "b/")):
                value = value[2:]
            paths.append(value)
        elif line.startswith("diff --git "):
            parts = line.split()
            for value in parts[2:4]:
                if value.startswith(("a/", "b/")):
                    value = value[2:]
                paths.append(value)
    return sorted(set(paths))


def validate_patch_paths(root: Path, patch: str) -> list[str]:
    changed: list[str] = []
    for path in extract_patch_paths(patch):
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise SecurityError(f"patch 包含非法路径: {path}")
        target = ensure_safe_path(root, path)
        changed.append(relative_to_root(root, target))
    return sorted(set(changed))


def command_is_dangerous(command: str) -> bool:
    """识别开发文档列出的第一阶段禁止命令模式。"""

    return any(pattern.search(command) for pattern in DANGEROUS_COMMAND_PATTERNS)


def run_subprocess(
    command: str | list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
    shell: bool = False,
    max_chars: int = 12000,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            shell=shell,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout, stdout_truncated = truncate_text(exc.stdout or "", max_chars)
        stderr, stderr_truncated = truncate_text(exc.stderr or "", max_chars)
        return {
            "ok": False,
            "error_type": "retryable_error",
            "message": f"命令超时: {timeout_seconds}s",
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": None,
            "truncated": stdout_truncated or stderr_truncated,
        }

    stdout, stdout_truncated = truncate_text(completed.stdout, max_chars)
    stderr, stderr_truncated = truncate_text(completed.stderr, max_chars)
    return {
        "ok": completed.returncode == 0,
        "error_type": None if completed.returncode == 0 else "retryable_error",
        "message": "" if completed.returncode == 0 else f"命令退出码非 0: {completed.returncode}",
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": completed.returncode,
        "truncated": stdout_truncated or stderr_truncated,
    }


def parse_tool_result(raw: str) -> ToolResult:
    return ToolResult.model_validate(json.loads(raw))
