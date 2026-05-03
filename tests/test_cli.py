from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Sequence
from unittest.mock import patch

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool

from code_agent.cli import main
from code_agent.models import ModelCompletion, ModelToolCall, TokenUsage


def _final(content: str) -> str:
    return json.dumps(
        {"role": "assistant", "type": "final_answer", "content": content},
        ensure_ascii=False,
    )


def _summary(content: str) -> str:
    return json.dumps(
        {"role": "assistant", "type": "summary", "content": content},
        ensure_ascii=False,
    )


class FakeProvider:
    name = "fake"

    def __init__(self, responses: list[str | ModelCompletion] | None = None) -> None:
        self.responses = responses or [_final("default provider response")]
        self.message_batches: list[list[BaseMessage]] = []

    def complete(
        self,
        messages: Sequence[BaseMessage],
        *,
        model: str,
        tools: Sequence[BaseTool] | None = None,
    ) -> ModelCompletion:
        self.message_batches.append(list(messages))
        if not self.responses:
            raise AssertionError("provider called too many times")
        response = self.responses.pop(0)
        if isinstance(response, ModelCompletion):
            return response
        return ModelCompletion(text=response)

    @property
    def prompts(self) -> list[str]:
        return ["\n".join(str(message.content) for message in batch) for batch in self.message_batches]


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
                patch("code_agent.cli._read_input", side_effect=["/exit"]),
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
            provider = FakeProvider(['{"skills":[]}', _final("default provider response")])
            with (
                patch("code_agent.cli._read_input", side_effect=["总结项目", "/quit"]),
                patch("code_agent.agent.make_provider", return_value=provider) as make_provider,
                redirect_stdout(stdout),
                redirect_stderr(StringIO()),
            ):
                exit_code = main(["--workspace", str(root), "--no-session"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(make_provider.call_count, 1)
            make_provider.assert_called_once_with("openai")
            self.assertIn("default provider response", stdout.getvalue())
            self.assertIn("Task", stdout.getvalue())
            self.assertIn("总结项目", stdout.getvalue())
            self.assertIn("Final Answer", stdout.getvalue())

    def test_interactive_reuses_memory_until_clear_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = FakeProvider([_final("first answer"), _final("second answer"), _final("third answer")])

            with (
                patch(
                    "code_agent.cli._read_input",
                    side_effect=["first task", "second task", "/clear", "third task", "/quit"],
                ),
                patch("code_agent.agent.make_provider", return_value=provider),
                redirect_stdout(StringIO()),
                redirect_stderr(StringIO()),
            ):
                exit_code = main(["--workspace", str(root), "--provider", "offline", "--no-session"])

            self.assertEqual(exit_code, 0)
            self.assertIn('"content": "first answer"', provider.prompts[1])
            self.assertNotIn("first task", provider.prompts[2])
            self.assertNotIn("second task", provider.prompts[2])

    def test_interactive_compact_and_memory_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = FakeProvider(
                [
                    _final("first answer"),
                    _final("second answer"),
                    _final("third answer"),
                    _final("remembered first"),
                ]
            )
            stdout = StringIO()

            with (
                patch(
                    "code_agent.cli._read_input",
                    side_effect=[
                        "first task",
                        "second task",
                        "third task",
                        "/compact",
                        "/memory",
                        "/quit",
                    ],
                ),
                patch("code_agent.agent.make_provider", return_value=provider),
                redirect_stdout(stdout),
                redirect_stderr(StringIO()),
            ):
                exit_code = main(["--workspace", str(root), "--provider", "offline", "--no-session"])

            self.assertEqual(exit_code, 0)
            self.assertIn("Compacted memory", stdout.getvalue())
            self.assertIn("remembered first", stdout.getvalue())

    def test_interactive_renders_token_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = FakeProvider(
                [
                    ModelCompletion(
                        text=_final("answer"),
                        usage=TokenUsage(prompt_tokens=8, completion_tokens=3, total_tokens=11),
                    )
                ]
            )
            stdout = StringIO()

            with (
                patch("code_agent.cli._read_input", side_effect=["task", "/quit"]),
                patch("code_agent.agent.make_provider", return_value=provider),
                redirect_stdout(stdout),
                redirect_stderr(StringIO()),
            ):
                exit_code = main(["--workspace", str(root), "--provider", "offline", "--no-session"])

            self.assertEqual(exit_code, 0)
            self.assertIn("Token Usage", stdout.getvalue())
            self.assertIn("total: 11", stdout.getvalue())

    def test_interactive_shell_command_can_be_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = FakeProvider(
                [
                    ModelCompletion(
                        text=_summary("需要运行命令。"),
                        tool_calls=[
                            ModelToolCall(
                                id="call_shell",
                                name="run_shell",
                                args={"command": "printf hello > out.txt"},
                            )
                        ],
                    ),
                    _final("not run"),
                ]
            )

            stdout = StringIO()
            with (
                patch("code_agent.cli._read_input", side_effect=["运行命令", "n", "/exit"]),
                patch("code_agent.agent.make_provider", return_value=provider),
                redirect_stdout(stdout),
                redirect_stderr(StringIO()),
            ):
                exit_code = main(["--workspace", str(root), "--provider", "offline", "--no-session"])

            self.assertEqual(exit_code, 0)
            self.assertFalse((root / "out.txt").exists())
            self.assertIn("Tool Call", stdout.getvalue())
            self.assertIn("command requires user approval", stdout.getvalue())
            self.assertIn("Final Answer", stdout.getvalue())
            self.assertIn("not run", stdout.getvalue())

    def test_interactive_shell_command_can_be_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = FakeProvider(
                [
                    ModelCompletion(
                        text=_summary("需要运行命令。"),
                        tool_calls=[
                            ModelToolCall(
                                id="call_shell",
                                name="run_shell",
                                args={"command": "printf hello > out.txt"},
                            )
                        ],
                    ),
                    _final("ran"),
                ]
            )

            stdout = StringIO()
            with (
                patch("code_agent.cli._read_input", side_effect=["运行命令", "y", "/exit"]),
                patch("code_agent.agent.make_provider", return_value=provider),
                redirect_stdout(stdout),
                redirect_stderr(StringIO()),
            ):
                exit_code = main(["--workspace", str(root), "--provider", "offline", "--no-session"])

            self.assertEqual(exit_code, 0)
            self.assertEqual((root / "out.txt").read_text(encoding="utf-8"), "hello")
            self.assertIn("Final Answer", stdout.getvalue())
            self.assertIn("ran", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
