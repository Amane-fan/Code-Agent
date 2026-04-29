from __future__ import annotations

import subprocess
from pathlib import Path

from code_agent.models import ContextFile, WorkspaceContext
from code_agent.security import is_sensitive_path, redact_secrets


LANGUAGE_BY_SUFFIX = {
    ".c": "C",
    ".cpp": "C++",
    ".css": "CSS",
    ".go": "Go",
    ".html": "HTML",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "React JSX",
    ".json": "JSON",
    ".md": "Markdown",
    ".py": "Python",
    ".rs": "Rust",
    ".sh": "Shell",
    ".toml": "TOML",
    ".ts": "TypeScript",
    ".tsx": "React TSX",
    ".yaml": "YAML",
    ".yml": "YAML",
}

PRIORITY_NAMES = {
    "readme.md": 8,
    "pyproject.toml": 8,
    "package.json": 8,
    "cargo.toml": 8,
    "go.mod": 8,
    "requirements.txt": 7,
    "main.py": 6,
    "app.py": 6,
    "cli.py": 6,
}


def collect_workspace_context(
    workspace_root: Path,
    prompt: str,
    *,
    max_files: int,
    max_file_bytes: int,
    max_context_chars: int,
) -> WorkspaceContext:
    """收集并排序模型需要的 workspace 上下文。"""

    root = workspace_root.expanduser().resolve()
    candidates = list(_candidate_files(root, max_file_bytes=max_file_bytes))
    # 先用轻量启发式排序，MVP 阶段不依赖向量库也能选出较相关的文件。
    ranked = sorted(
        (
            ContextFile(
                path=_relative(root, path),
                score=_score(path, prompt),
                language=_language(path),
                content=_read_text(path, max_file_bytes),
            )
            for path in candidates
        ),
        key=lambda file: (-file.score, file.path),
    )
    selected: list[ContextFile] = []
    used_chars = 0
    for file in ranked:
        # 控制上下文体积，避免一次请求把大仓库全部塞给模型。
        projected = used_chars + len(file.content)
        if selected and projected > max_context_chars:
            continue
        selected.append(file)
        used_chars += len(file.content)
        if len(selected) >= max_files:
            break

    return WorkspaceContext(root=root, prompt=prompt, git_status=_git_status(root), files=selected)


def collect_repo_context(
    repo_root: Path,
    prompt: str,
    *,
    max_files: int,
    max_file_bytes: int,
    max_context_chars: int,
) -> WorkspaceContext:
    """向后兼容旧名称；新代码应使用 collect_workspace_context。"""

    return collect_workspace_context(
        repo_root,
        prompt,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        max_context_chars=max_context_chars,
    )


def _candidate_files(root: Path, *, max_file_bytes: int) -> list[Path]:
    files: list[Path] = []
    # Git 仓库优先使用 tracked + untracked non-ignored 文件，避免把缓存目录扫进来。
    tracked = _git_ls_files(root)
    source = tracked if tracked else [path for path in root.rglob("*") if path.is_file()]
    for path in source:
        full_path = root / path if not path.is_absolute() else path
        relative_path = full_path.relative_to(root) if full_path.is_relative_to(root) else full_path
        if is_sensitive_path(relative_path):
            # 敏感路径在上下文收集阶段直接跳过，防止泄露到模型请求或会话日志。
            continue
        try:
            if full_path.stat().st_size > max_file_bytes:
                continue
        except OSError:
            continue
        files.append(full_path)
    return files


def _git_ls_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def _git_status(root: Path) -> str:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return "git status unavailable"
    return result.stdout


def _read_text(path: Path, max_file_bytes: int) -> str:
    try:
        data = path.read_bytes()[:max_file_bytes]
    except OSError as exc:
        return f"[unreadable: {exc}]"
    if b"\x00" in data:
        return "[binary file skipped]"
    return redact_secrets(data.decode("utf-8", errors="replace"))


def _score(path: Path, prompt: str) -> int:
    """根据文件名、路径和用户任务关键词计算相关性分数。"""

    lowered_prompt = prompt.lower()
    relative = str(path).lower()
    name = path.name.lower()
    score = PRIORITY_NAMES.get(name, 0)
    for term in _terms(lowered_prompt):
        if term in relative:
            score += 8
        if term in name:
            score += 12
    if path.suffix.lower() in LANGUAGE_BY_SUFFIX:
        score += 2
    if "test" in name or "/test" in relative:
        score += 1
    return score


def _terms(prompt: str) -> set[str]:
    raw = "".join(char if char.isalnum() or char in "_-" else " " for char in prompt)
    return {term for term in raw.split() if len(term) >= 3}


def _language(path: Path) -> str:
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower(), "Text")


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
