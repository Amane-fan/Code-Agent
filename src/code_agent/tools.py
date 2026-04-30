from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from code_agent.models import ToolResult
from code_agent.security import (
    ensure_within_workspace,
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
                    "read_file",
                    False,
                    error=f"refusing to read sensitive path: {rel}",
                )
            data = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return ToolResult("read_file", False, error=str(exc))
        return ToolResult(
            "read_file",
            True,
            output=redact_secrets(data),
            metadata={"path": relative_path},
        )

    def write(self, relative_path: str, content: str) -> ToolResult:
        try:
            path = ensure_within_workspace(self.workspace_root, Path(relative_path))
            rel = path.relative_to(self.workspace_root)
            if is_sensitive_path(rel):
                return ToolResult(
                    "write_file",
                    False,
                    error=f"refusing to write sensitive path: {rel}",
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except Exception as exc:
            return ToolResult("write_file", False, error=str(exc))
        return ToolResult(
            "write_file",
            True,
            output=f"wrote {relative_path} ({len(content.encode('utf-8'))} bytes)",
            metadata={"path": relative_path},
        )

    def edit(self, relative_path: str, old_text: str, new_text: str) -> ToolResult:
        try:
            path = ensure_within_workspace(self.workspace_root, Path(relative_path))
            rel = path.relative_to(self.workspace_root)
            if is_sensitive_path(rel):
                return ToolResult(
                    "edit_file",
                    False,
                    error=f"refusing to edit sensitive path: {rel}",
                )
            data = path.read_text(encoding="utf-8")
            matches = data.count(old_text)
            if matches != 1:
                return ToolResult(
                    "edit_file",
                    False,
                    error=f"old_text must be unique; found {matches} matches",
                    metadata={"path": relative_path, "matches": matches},
                )
            updated = data.replace(old_text, new_text, 1)
            path.write_text(updated, encoding="utf-8")
        except Exception as exc:
            return ToolResult("edit_file", False, error=str(exc))
        return ToolResult(
            "edit_file",
            True,
            output=f"edited {relative_path}",
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
        return ToolResult("list_files", True, output="\n".join(files))

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
        return ToolResult("grep_search", True, output=redact_secrets("\n".join(matches)))


@dataclass(frozen=True)
class ShellTool:
    """受用户确认保护的 shell 工具。"""

    workspace_root: Path

    def run(
        self,
        command: str,
        *,
        approved: bool = False,
        timeout: int = 120,
    ) -> ToolResult:
        if not approved:
            return ToolResult(
                "run_shell",
                False,
                error=f"command requires user approval: {command}",
                metadata={"command": command},
            )
        try:
            result = subprocess.run(
                ["/bin/bash", "-lc", command],
                cwd=self.workspace_root,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except Exception as exc:
            return ToolResult("run_shell", False, error=str(exc), metadata={"command": command})
        output = "\n".join(part for part in [result.stdout, result.stderr] if part)
        return ToolResult(
            "run_shell",
            result.returncode == 0,
            output=redact_secrets(output),
            metadata={"command": command, "returncode": result.returncode},
        )
