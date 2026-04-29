from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from code_agent.models import ToolResult


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

    repo_root: Path

    def check(self, patch: str) -> ToolResult:
        return self._git_apply(patch, check=True)

    def apply(self, patch: str) -> ToolResult:
        return self._git_apply(patch, check=False)

    def _git_apply(self, patch: str, *, check: bool) -> ToolResult:
        args = ["git", "apply"]
        if check:
            # --check 只验证补丁是否能应用，不会修改工作区。
            args.append("--check")
        result = subprocess.run(
            args,
            cwd=self.repo_root,
            input=patch,
            text=True,
            capture_output=True,
            check=False,
        )
        name = "patch.check" if check else "patch.apply"
        return ToolResult(
            name=name,
            ok=result.returncode == 0,
            output=result.stdout,
            error=result.stderr,
            metadata={"returncode": result.returncode},
        )
