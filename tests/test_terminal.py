from __future__ import annotations

import unittest
from unittest.mock import patch

from prompt_toolkit.document import Document

from code_agent.terminal import SlashCommandCompleter, read_prompt


class TerminalTests(unittest.TestCase):
    def test_slash_command_completer_suggests_control_commands(self) -> None:
        completer = SlashCommandCompleter(["/exit", "/quit", "/compact", "/memory", "/clear"])
        completions = list(completer.get_completions(Document("/c", cursor_position=2), None))

        self.assertEqual([completion.text for completion in completions], ["/compact", "/clear"])

    def test_read_prompt_uses_prompt_toolkit_session(self) -> None:
        with patch("code_agent.terminal.PromptSession") as prompt_session:
            prompt_session.return_value.prompt.return_value = "检查 README"

            result = read_prompt("code-agent> ")

        self.assertEqual(result, "检查 README")
        prompt_session.return_value.prompt.assert_called_once_with("code-agent> ")


if __name__ == "__main__":
    unittest.main()
