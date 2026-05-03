from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from code_agent.models import ToolResult
from code_agent.security import redact_secrets
from code_agent.terminal import preserve_stdin_terminal
from code_agent.tools.base import JsonSchema, Tool, required_str


@dataclass(frozen=True)
class ShellTool:
    """受用户显式确认保护的 shell 命令执行器。"""

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


class RunShellTool(Tool):
    name = "run_shell"
    description = "Request a shell command in the workspace."
    parameters_schema: ClassVar[JsonSchema] = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run."},
        },
        "required": ["command"],
        "additionalProperties": False,
    }
    returns_schema: ClassVar[JsonSchema] = {
        "type": "object",
        "description": (
            "Returns combined stdout/stderr in output and metadata.command plus "
            "metadata.returncode. The command only runs if the user approves it; otherwise "
            "ok is false and error says approval is required."
        ),
        "properties": {
            "output": {"type": "string", "description": "Combined stdout/stderr."},
            "error": {"type": "string", "description": "Failure reason."},
            "metadata": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "returncode": {"type": "integer"},
                },
            },
        },
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        command = required_str(self.name, args, "command")
        approved = (
            self.context.shell_approval(command)
            if self.context.shell_approval is not None
            else False
        )
        return ShellTool(self.context.workspace_root).run(command, approved=approved)
