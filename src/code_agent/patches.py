from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from code_agent.models import ToolResult
from code_agent.security import ensure_within_workspace, is_sensitive_path


DIFF_BLOCK_RE = re.compile(r"```(?:diff|patch)?\s*\n(?P<diff>diff --git .*?)```", re.DOTALL)


def extract_unified_diff(text: str) -> str | None:
    """从模型回复中提取 git-apply 兼容的 unified diff。"""

    match = DIFF_BLOCK_RE.search(text)
    if match:
        return match.group("diff").strip() + "\n"
    start = text.find("diff --git ")
    if start == -1:
        return None
    return text[start:].strip() + "\n"


@dataclass(frozen=True)
class PatchTool:
    """补丁工具统一通过 git apply 校验和应用，避免手写文件修改逻辑。"""

    workspace_root: Path

    def check(self, patch: str) -> ToolResult:
        return self._git_apply(patch, check=True)

    def apply(self, patch: str) -> ToolResult:
        return self._git_apply(patch, check=False)

    def _git_apply(self, patch: str, *, check: bool) -> ToolResult:
        name = "patch.check" if check else "patch.apply"
        invalid = self._validate_patch_paths(patch, name=name)
        if invalid is not None:
            return invalid

        args = ["git", "apply"]
        if check:
            # --check 只验证补丁是否能应用，不会修改工作区。
            args.append("--check")
        result = subprocess.run(
            args,
            cwd=self.workspace_root,
            input=patch,
            text=True,
            capture_output=True,
            check=False,
        )
        return ToolResult(
            name=name,
            ok=result.returncode == 0,
            output=result.stdout,
            error=result.stderr,
            metadata={"returncode": result.returncode},
        )

    def _validate_patch_paths(self, patch: str, *, name: str) -> ToolResult | None:
        for path_text in _diff_paths(patch):
            path = _normalize_diff_path(path_text)
            if path is None:
                continue
            candidate = Path(path)
            if candidate.is_absolute() or ".." in candidate.parts:
                return ToolResult(
                    name=name,
                    ok=False,
                    error=f"patch path escapes workspace: {path_text}",
                )
            try:
                resolved = ensure_within_workspace(self.workspace_root, candidate)
                relative = resolved.relative_to(self.workspace_root.resolve())
            except Exception:
                return ToolResult(
                    name=name,
                    ok=False,
                    error=f"patch path escapes workspace: {path_text}",
                )
            if is_sensitive_path(relative):
                return ToolResult(
                    name=name,
                    ok=False,
                    error=f"refusing to patch sensitive path: {relative}",
                )
        return None


def _diff_paths(patch: str) -> list[str]:
    paths: list[str] = []
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            try:
                parts = shlex.split(line.removeprefix("diff --git "))
            except ValueError:
                continue
            paths.extend(parts[:2])
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            token = line[4:].split("\t", 1)[0].strip()
            if token:
                paths.append(token)
    return paths


def _normalize_diff_path(path_text: str) -> str | None:
    if path_text == "/dev/null":
        return None
    if path_text.startswith("a/") or path_text.startswith("b/"):
        return path_text[2:]
    return path_text
