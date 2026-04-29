from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_agent.tools import FileTools, ShellTool, detect_test_command


class ToolTests(unittest.TestCase):
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

    def test_shell_tool_requires_safe_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = ShellTool(Path(tmp)).run("rm -rf .")
            self.assertFalse(result.ok)

    def test_detect_test_command_for_python_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            (root / "tests").mkdir()
            self.assertEqual(detect_test_command(root), "python -m unittest discover -s tests")

    def test_detect_test_command_for_pytest_project_without_tests_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            self.assertEqual(detect_test_command(root), "python -m pytest")


if __name__ == "__main__":
    unittest.main()
