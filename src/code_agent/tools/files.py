from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from code_agent.models import ToolResult
from code_agent.security import ensure_within_workspace, is_sensitive_path, redact_secrets
from code_agent.tools.base import JsonSchema, ToolContext


TEXT_PATH_SCHEMA: JsonSchema = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Workspace-relative path to a non-sensitive UTF-8 text file.",
        },
    },
    "required": ["path"],
    "additionalProperties": False,
}

FILE_RESULT_SCHEMA: JsonSchema = {
    "type": "object",
    "properties": {
        "output": {
            "type": "string",
            "description": "Human-readable tool output, such as redacted file contents.",
        },
        "error": {"type": "string", "description": "Failure reason when ok is false."},
        "metadata": {
            "type": "object",
            "description": "Structured details such as the requested path.",
        },
    },
}


@dataclass(frozen=True)
class FileTools:
    """受路径和安全检查保护的 workspace 文件操作。"""

    workspace_root: Path

    def read(self, relative_path: str) -> ToolResult:
        try:
            path = ensure_within_workspace(self.workspace_root, Path(relative_path))
            rel = path.relative_to(self.workspace_root)
            if is_sensitive_path(rel):
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


def create_tools(context: ToolContext) -> list[BaseTool]:
    files = FileTools(context.workspace_root)

    @tool("read_file")
    def read_file(path: str) -> ToolResult:
        """Read one non-sensitive UTF-8 text file inside the workspace."""

        return files.read(path)

    @tool("write_file")
    def write_file(path: str, content: str) -> ToolResult:
        """Create or overwrite one non-sensitive UTF-8 text file inside the workspace."""

        return files.write(path, content)

    @tool("edit_file")
    def edit_file(path: str, old_text: str, new_text: str) -> ToolResult:
        """Replace text in one non-sensitive UTF-8 text file inside the workspace."""

        return files.edit(path, old_text, new_text)

    @tool("list_files")
    def list_files() -> ToolResult:
        """List non-sensitive files inside the workspace."""

        return files.list()

    @tool("grep_search")
    def grep_search(pattern: str) -> ToolResult:
        """Search non-sensitive text files inside the workspace, case-insensitively."""

        return files.search(pattern)

    return [read_file, write_file, edit_file, list_files, grep_search]
