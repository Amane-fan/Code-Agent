from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from code_agent.models import ToolResult
from code_agent.security import (
    ensure_within_workspace,
    is_sensitive_path,
    redact_secrets,
)
from code_agent.skills import SkillRegistry
from code_agent.terminal import preserve_stdin_terminal

ToolHandler = Callable[[dict[str, Any]], ToolResult]
ShellApproval = Callable[[str], bool]


@dataclass(frozen=True)
class ToolSpec:
    """工具执行和系统提示词文档的单一来源。"""

    name: str
    description: str
    args_schema: str
    returns: str
    handler: ToolHandler


class ToolRegistry:
    """按名称分发工具调用，并暴露启动时可渲染的工具说明。"""

    def __init__(self, specs: Sequence[ToolSpec]) -> None:
        tools: dict[str, ToolSpec] = {}
        for spec in specs:
            if spec.name in tools:
                raise ValueError(f"duplicate tool name: {spec.name}")
            tools[spec.name] = spec
        self._tools = tools

    @property
    def specs(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        spec = self._tools.get(name)
        if spec is None:
            return ToolResult(name, False, error=f"unknown tool: {name}")
        try:
            return spec.handler(args)
        except ValueError as exc:
            return ToolResult(name, False, error=str(exc), metadata={"args": args})


def create_workspace_tool_registry(
    workspace_root: Path,
    *,
    skill_registry: SkillRegistry | None = None,
    shell_approval: ShellApproval | None = None,
) -> ToolRegistry:
    """创建绑定到单一 workspace 的默认工具注册表。"""

    file_tools = FileTools(workspace_root)
    shell_tool = ShellTool(workspace_root)
    skills = skill_registry or SkillRegistry.empty()

    def read_file(args: dict[str, Any]) -> ToolResult:
        return file_tools.read(_required_str("read_file", args, "path"))

    def write_file(args: dict[str, Any]) -> ToolResult:
        return file_tools.write(
            _required_str("write_file", args, "path"),
            _required_str("write_file", args, "content"),
        )

    def edit_file(args: dict[str, Any]) -> ToolResult:
        return file_tools.edit(
            _required_str("edit_file", args, "path"),
            _required_str("edit_file", args, "old_text"),
            _required_str("edit_file", args, "new_text"),
        )

    def list_files(args: dict[str, Any]) -> ToolResult:
        _reject_args("list_files", args)
        return file_tools.list()

    def grep_search(args: dict[str, Any]) -> ToolResult:
        return file_tools.search(_required_str("grep_search", args, "pattern"))

    def run_shell(args: dict[str, Any]) -> ToolResult:
        command = _required_str("run_shell", args, "command")
        approved = shell_approval(command) if shell_approval is not None else False
        return shell_tool.run(command, approved=approved)

    def load_skill(args: dict[str, Any]) -> ToolResult:
        name = _required_str("load_skill", args, "name")
        try:
            loaded = skills.load(name)
        except KeyError:
            return ToolResult(
                "load_skill",
                False,
                error=f"unknown skill: {name}",
                metadata={"available_skills": skills.names()},
            )
        return ToolResult(
            "load_skill",
            True,
            output=loaded.content,
            metadata={"name": loaded.metadata.name, "path": str(loaded.path)},
        )

    return ToolRegistry(
        [
            ToolSpec(
                name="read_file",
                description="Read one non-sensitive UTF-8 text file inside the workspace.",
                args_schema='{"path":"relative/path"}',
                returns="redacted file contents in output and the requested path in metadata.path. "
                "On failure, error explains why the file could not be read.",
                handler=read_file,
            ),
            ToolSpec(
                name="write_file",
                description="Create or overwrite one non-sensitive UTF-8 text file inside the workspace.",
                args_schema='{"path":"relative/path","content":"..."}',
                returns="the written path and byte count in output, plus metadata.path. "
                "On failure, error explains why the file could not be written.",
                handler=write_file,
            ),
            ToolSpec(
                name="edit_file",
                description="Replace text in one non-sensitive UTF-8 text file inside the workspace.",
                args_schema='{"path":"relative/path","old_text":"...","new_text":"..."}',
                returns="an edit confirmation in output and metadata.path. old_text must match "
                "exactly once; otherwise ok is false and error explains the match problem.",
                handler=edit_file,
            ),
            ToolSpec(
                name="list_files",
                description="List non-sensitive files inside the workspace.",
                args_schema="{}",
                returns="newline-separated relative paths in output. Sensitive files and skipped "
                "directories are omitted.",
                handler=list_files,
            ),
            ToolSpec(
                name="grep_search",
                description="Search non-sensitive text files inside the workspace, case-insensitively.",
                args_schema='{"pattern":"text"}',
                returns="matching lines in output using path:line: text format. Secret-looking "
                "values are redacted.",
                handler=grep_search,
            ),
            ToolSpec(
                name="run_shell",
                description="Request a shell command in the workspace.",
                args_schema='{"command":"shell command"}',
                returns="combined stdout/stderr in output and metadata.command plus "
                "metadata.returncode. The command only runs if the user approves it; "
                "otherwise ok is false and error says approval is required.",
                handler=run_shell,
            ),
            ToolSpec(
                name="load_skill",
                description="Load the full instructions for one startup-listed skill by name.",
                args_schema='{"name":"skill_name"}',
                returns="full skill instructions in output and metadata.name plus metadata.path. "
                "On failure, error explains the unknown skill and metadata.available_skills "
                "lists valid names.",
                handler=load_skill,
            ),
        ]
    )


def _required_str(tool: str, args: dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str):
        raise ValueError(f"{tool}.{name} must be a string")
    return value


def _reject_args(tool: str, args: dict[str, Any]) -> None:
    if args:
        raise ValueError(f"{tool} does not accept arguments")


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
            with preserve_stdin_terminal():
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
