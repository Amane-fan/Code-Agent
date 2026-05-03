from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from code_agent.models import ToolResult
from code_agent.security import redact_secrets
from code_agent.terminal import preserve_stdin_terminal
from code_agent.tools.base import ToolContext


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


def create_tools(context: ToolContext) -> list[BaseTool]:
    shell = ShellTool(context.workspace_root)

    @tool("run_shell")
    def run_shell(command: str) -> ToolResult:
        """Request a shell command in the workspace; every invocation asks for approval."""

        approved = (
            context.shell_approval(command)
            if context.shell_approval is not None
            else False
        )
        return shell.run(command, approved=approved)

    return [run_shell]
