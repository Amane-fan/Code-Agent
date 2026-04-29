from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from code_agent.cli import main
from code_agent.models import RepoContext


class FakeProvider:
    name = "fake"

    def complete(self, prompt: str, context: RepoContext, *, model: str) -> str:
        return "default provider response"


class CliTests(unittest.TestCase):
    def test_tool_run_keeps_top_level_command_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_dummy.py").write_text(
                "import unittest\n\n"
                "class DummyTest(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = main(
                    [
                        "tool",
                        "run",
                        "python -m unittest discover -s tests",
                        "--repo",
                        str(root),
                    ]
                )
            self.assertEqual(exit_code, 0)

    def test_ask_defaults_to_openai_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            stdout = StringIO()
            with (
                patch("code_agent.graph.make_provider", return_value=FakeProvider()) as make_provider,
                redirect_stdout(stdout),
                redirect_stderr(StringIO()),
            ):
                exit_code = main(["ask", "总结项目", "--repo", str(root), "--no-session"])

            self.assertEqual(exit_code, 0)
            make_provider.assert_called_once_with("openai")
            self.assertIn("default provider response", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
