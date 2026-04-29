from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from code_agent.models import ToolResult
from code_agent.security import (
    ensure_within_workspace,
    is_safe_command,
    is_sensitive_path,
    redact_secrets,
)


@dataclass(frozen=True)
class FileTools:
    """Workspace 文件工具，所有读取都会经过路径和敏感文件校验。"""

    workspace_root: Path

    def read(self, relative_path: str) -> ToolResult:
        try:
            path = ensure_within_workspace(self.workspace_root, Path(relative_path))
            rel = path.relative_to(self.workspace_root)
            if is_sensitive_path(rel):
                # 文件名命中敏感规则时直接拒绝读取，避免把凭据暴露给 Agent。
                return ToolResult(
                    "file.read",
                    False,
                    error=f"refusing to read sensitive path: {rel}",
                )
            data = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return ToolResult("file.read", False, error=str(exc))
        return ToolResult(
            "file.read",
            True,
            output=redact_secrets(data),
            metadata={"path": relative_path},
        )

    def list(self) -> ToolResult:
        files: list[str] = []
        for path in sorted(self.workspace_root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self.workspace_root)
            if is_sensitive_path(rel):
                continue
            files.append(str(rel))
        return ToolResult("file.list", True, output="\n".join(files))

    def search(self, pattern: str) -> ToolResult:
        matches: list[str] = []
        lowered = pattern.lower()
        # MVP 使用标准库遍历文本；后续可以替换为 ripgrep 或符号索引。
        for path in sorted(self.workspace_root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self.workspace_root)
            if is_sensitive_path(rel):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if lowered in line.lower():
                    matches.append(f"{rel}:{line_number}: {line}")
        return ToolResult("file.search", True, output=redact_secrets("\n".join(matches)))


@dataclass(frozen=True)
class ShellTool:
    """受限 shell 工具，默认只允许安全白名单里的命令。"""

    workspace_root: Path

    def run(self, command: str, *, allow_unsafe: bool = False, timeout: int = 120) -> ToolResult:
        argv = shlex.split(command)
        if not allow_unsafe and not is_safe_command(argv):
            # 破坏性或未知命令需要显式 --unsafe，避免 Agent 默认执行高风险操作。
            return ToolResult(
                "shell.run",
                False,
                error=f"command requires approval or --unsafe: {command}",
                metadata={"argv": argv},
            )
        try:
            result = subprocess.run(
                argv,
                cwd=self.workspace_root,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except Exception as exc:
            return ToolResult("shell.run", False, error=str(exc), metadata={"argv": argv})
        output = "\n".join(part for part in [result.stdout, result.stderr] if part)
        return ToolResult(
            "shell.run",
            result.returncode == 0,
            output=redact_secrets(output),
            metadata={"argv": argv, "returncode": result.returncode},
        )


def detect_test_command(workspace_root: Path) -> str | None:
    """根据 workspace 特征推断最可能的测试命令。"""

    if (workspace_root / "tests").is_dir():
        return "python -m unittest discover -s tests"
    if (workspace_root / "pyproject.toml").exists() or (workspace_root / "pytest.ini").exists():
        return "python -m pytest"
    if (workspace_root / "package.json").exists():
        return "npm test"
    if (workspace_root / "Cargo.toml").exists():
        return "cargo test"
    if (workspace_root / "go.mod").exists():
        return "go test ./..."
    return None
