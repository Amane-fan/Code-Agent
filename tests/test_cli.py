from __future__ import annotations

import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from code_agent.cli import main
from code_agent.models import WorkspaceContext


class FakeProvider:
    name = "fake"

    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = responses or ["<summary>完成。</summary>\n<final_answer>default provider response</final_answer>"]
        self.prompts: list[str] = []

    def complete(self, prompt: str, context: WorkspaceContext, *, model: str) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("provider called too many times")
        return self.responses.pop(0)


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)


class CliTests(unittest.TestCase):
    def test_workspace_is_required(self) -> None:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            exit_code = main([])

        self.assertEqual(exit_code, 2)

    def test_old_subcommands_are_not_valid_entrypoints(self) -> None:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            exit_code = main(["ask", "总结项目"])

        self.assertEqual(exit_code, 2)

    def test_exit_command_leaves_interactive_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch("builtins.input", side_effect=["/exit"]),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                exit_code = main(["--workspace", tmp, "--provider", "offline", "--no-session"])

        self.assertEqual(exit_code, 0)

    def test_interactive_defaults_to_openai_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            stdout = StringIO()
            provider = FakeProvider()
            with (
                patch("builtins.input", side_effect=["总结项目", "/quit"]),
                patch("code_agent.agent.make_provider", return_value=provider) as make_provider,
                redirect_stdout(stdout),
                redirect_stderr(StringIO()),
            ):
                exit_code = main(["--workspace", str(root), "--no-session"])

            self.assertEqual(exit_code, 0)
            make_provider.assert_called_once_with("openai")
            self.assertIn("default provider response", stdout.getvalue())
            self.assertIn("<task>总结项目</task>", stdout.getvalue())
            self.assertIn("<summary>完成。</summary>", stdout.getvalue())
            self.assertIn("<final_answer>default provider response</final_answer>", stdout.getvalue())

    def test_interactive_shell_command_can_be_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = FakeProvider(
                [
                    '<summary>需要运行命令。</summary>\n'
                    '<action>{"tool":"run_shell","args":{"command":"printf hello > out.txt"}}</action>',
                    "<summary>命令被拒绝，停止。</summary>\n<final_answer>not run</final_answer>",
                ]
            )

            stdout = StringIO()
            with (
                patch("builtins.input", side_effect=["运行命令", "n", "/exit"]),
                patch("code_agent.agent.make_provider", return_value=provider),
                redirect_stdout(stdout),
                redirect_stderr(StringIO()),
            ):
                exit_code = main(["--workspace", str(root), "--no-session"])

            self.assertEqual(exit_code, 0)
            self.assertFalse((root / "out.txt").exists())
            self.assertIn("<action>", stdout.getvalue())
            self.assertIn("command requires user approval", stdout.getvalue())
            self.assertIn("<final_answer>not run</final_answer>", stdout.getvalue())

    def test_interactive_shell_command_can_be_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = FakeProvider(
                [
                    '<summary>需要运行命令。</summary>\n'
                    '<action>{"tool":"run_shell","args":{"command":"printf hello > out.txt"}}</action>',
                    "<summary>命令完成。</summary>\n<final_answer>ran</final_answer>",
                ]
            )

            stdout = StringIO()
            with (
                patch("builtins.input", side_effect=["运行命令", "y", "/exit"]),
                patch("code_agent.agent.make_provider", return_value=provider),
                redirect_stdout(stdout),
                redirect_stderr(StringIO()),
            ):
                exit_code = main(["--workspace", str(root), "--no-session"])

            self.assertEqual(exit_code, 0)
            self.assertEqual((root / "out.txt").read_text(encoding="utf-8"), "hello")
            self.assertIn("<final_answer>ran</final_answer>", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
