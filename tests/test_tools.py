from __future__ import annotations

import sys
import termios
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from code_agent.models import ToolResult
from code_agent.tools import FileTools, ShellTool, Tool, ToolContext, ToolRegistry


class ToolTests(unittest.TestCase):
    def test_tool_registry_executes_tool_subclasses_and_rejects_duplicates(self) -> None:
        class EchoTool(Tool):
            name = "echo"
            description = "Echo a message."
            parameters_schema = {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
                "additionalProperties": False,
            }
            returns_schema = {
                "type": "object",
                "properties": {"output": {"type": "string"}},
            }

            def run(self, args: dict[str, Any]) -> ToolResult:
                return ToolResult(self.name, True, output=str(args["message"]))

        class DuplicateEchoTool(EchoTool):
            pass

        context = ToolContext(workspace_root=Path.cwd())
        registry = ToolRegistry([EchoTool(context)])

        result = registry.execute("echo", {"message": "hello"})

        self.assertTrue(result.ok)
        self.assertEqual(result.output, "hello")
        with self.assertRaisesRegex(ValueError, "duplicate tool name: echo"):
            ToolRegistry([EchoTool(context), DuplicateEchoTool(context)])

    def test_workspace_registry_exposes_json_schemas_for_default_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = ToolRegistry.default(ToolContext(workspace_root=Path(tmp)))

            specs = {spec.name: spec for spec in registry.specs}

        self.assertIn("read_file", specs)
        self.assertEqual(specs["read_file"].parameters_schema["type"], "object")
        self.assertIn("path", specs["read_file"].parameters_schema["required"])
        self.assertEqual(specs["read_file"].returns_schema["type"], "object")

    def test_file_tools_refuse_sensitive_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
            result = FileTools(root).read(".env")
            self.assertFalse(result.ok)

    def test_file_tools_refuse_paths_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            outside = Path(tmp) / "outside.txt"
            outside.write_text("secret\n", encoding="utf-8")

            result = FileTools(root).read("../outside.txt")

            self.assertFalse(result.ok)

    def test_file_tools_write_file_creates_and_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = FileTools(root)

            created = tools.write("app.py", "print('hello')\n")
            overwritten = tools.write("app.py", "print('bye')\n")

            self.assertTrue(created.ok)
            self.assertTrue(overwritten.ok)
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "print('bye')\n")

    def test_file_tools_edit_requires_unique_old_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("value = 1\nvalue = 1\n", encoding="utf-8")
            tools = FileTools(root)

            ambiguous = tools.edit("app.py", "value = 1", "value = 2")
            precise = tools.edit("app.py", "value = 1\nvalue = 1\n", "value = 2\n")

            self.assertFalse(ambiguous.ok)
            self.assertIn("unique", ambiguous.error)
            self.assertTrue(precise.ok)
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "value = 2\n")

    def test_shell_tool_requires_approval_and_runs_via_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool = ShellTool(root)

            denied = tool.run("printf hello > out.txt", approved=False)
            allowed = tool.run("printf hello > out.txt", approved=True)

            self.assertFalse(denied.ok)
            self.assertIn("approval", denied.error)
            self.assertTrue(allowed.ok)
            self.assertEqual((root / "out.txt").read_text(encoding="utf-8"), "hello")

    def test_shell_tool_requires_safe_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = ShellTool(Path(tmp)).run("rm -rf .")
            self.assertFalse(result.ok)

    def test_shell_tool_restores_terminal_state_after_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved_attrs = ["saved-terminal-state"]

            with (
                patch.object(sys.stdin, "isatty", return_value=True),
                patch.object(sys.stdin, "fileno", return_value=42),
                patch("termios.tcgetattr", return_value=saved_attrs) as get_attrs,
                patch("termios.tcsetattr") as set_attrs,
            ):
                result = ShellTool(root).run("printf hello", approved=True)

            self.assertTrue(result.ok)
            get_attrs.assert_called_once_with(42)
            set_attrs.assert_called_once_with(42, termios.TCSADRAIN, saved_attrs)


if __name__ == "__main__":
    unittest.main()
