from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from code_agent.models import ToolResult
from code_agent.security import ensure_within_workspace, is_sensitive_path, redact_secrets
from code_agent.tools.base import JsonSchema, Tool, reject_args, required_str


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
    """Workspace file operations guarded by path and sensitivity checks."""

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


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read one non-sensitive UTF-8 text file inside the workspace."
    parameters_schema: ClassVar[JsonSchema] = TEXT_PATH_SCHEMA
    returns_schema: ClassVar[JsonSchema] = {
        **FILE_RESULT_SCHEMA,
        "description": "Returns redacted file contents in output and metadata.path.",
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        return FileTools(self.context.workspace_root).read(required_str(self.name, args, "path"))


class WriteFileTool(Tool):
    name = "write_file"
    description = "Create or overwrite one non-sensitive UTF-8 text file inside the workspace."
    parameters_schema: ClassVar[JsonSchema] = {
        "type": "object",
        "properties": {
            "path": TEXT_PATH_SCHEMA["properties"]["path"],
            "content": {"type": "string", "description": "UTF-8 text content to write."},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }
    returns_schema: ClassVar[JsonSchema] = {
        **FILE_RESULT_SCHEMA,
        "description": "Returns the written path and byte count in output plus metadata.path.",
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        files = FileTools(self.context.workspace_root)
        return files.write(
            required_str(self.name, args, "path"),
            required_str(self.name, args, "content"),
        )


class EditFileTool(Tool):
    name = "edit_file"
    description = "Replace text in one non-sensitive UTF-8 text file inside the workspace."
    parameters_schema: ClassVar[JsonSchema] = {
        "type": "object",
        "properties": {
            "path": TEXT_PATH_SCHEMA["properties"]["path"],
            "old_text": {
                "type": "string",
                "description": "Exact text to replace. It must match exactly once.",
            },
            "new_text": {"type": "string", "description": "Replacement text."},
        },
        "required": ["path", "old_text", "new_text"],
        "additionalProperties": False,
    }
    returns_schema: ClassVar[JsonSchema] = {
        **FILE_RESULT_SCHEMA,
        "description": (
            "Returns an edit confirmation in output and metadata.path. old_text must match "
            "exactly once; otherwise ok is false and error explains the match problem."
        ),
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        files = FileTools(self.context.workspace_root)
        return files.edit(
            required_str(self.name, args, "path"),
            required_str(self.name, args, "old_text"),
            required_str(self.name, args, "new_text"),
        )


class ListFilesTool(Tool):
    name = "list_files"
    description = "List non-sensitive files inside the workspace."
    parameters_schema: ClassVar[JsonSchema] = {}
    returns_schema: ClassVar[JsonSchema] = {
        "type": "object",
        "description": (
            "Returns newline-separated relative paths in output. Sensitive files and skipped "
            "directories are omitted."
        ),
        "properties": {
            "output": {"type": "string", "description": "Newline-separated relative paths."},
            "error": {"type": "string"},
            "metadata": {"type": "object"},
        },
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        reject_args(self.name, args)
        return FileTools(self.context.workspace_root).list()


class GrepSearchTool(Tool):
    name = "grep_search"
    description = "Search non-sensitive text files inside the workspace, case-insensitively."
    parameters_schema: ClassVar[JsonSchema] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Case-insensitive text to find."},
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }
    returns_schema: ClassVar[JsonSchema] = {
        "type": "object",
        "description": (
            "Returns matching lines in output using path:line: text format. Secret-looking "
            "values are redacted."
        ),
        "properties": {
            "output": {"type": "string", "description": "Matches in path:line: text format."},
            "error": {"type": "string"},
            "metadata": {"type": "object"},
        },
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        return FileTools(self.context.workspace_root).search(
            required_str(self.name, args, "pattern")
        )
