from __future__ import annotations

import unittest

from code_agent.providers import SYSTEM_INSTRUCTIONS


class PromptTests(unittest.TestCase):
    def test_system_prompt_keeps_english_protocol_examples(self) -> None:
        self.assertIn("You are a cautious terminal programming agent.", SYSTEM_INSTRUCTIONS)
        self.assertIn("<summary>Read README.md to inspect the project overview.</summary>", SYSTEM_INSTRUCTIONS)
        self.assertIn(
            '<action>{"tool":"read_file","args":{"path":"README.md"}}</action>',
            SYSTEM_INSTRUCTIONS,
        )
        self.assertIn(
            "<summary>The requested change has been completed and verified.</summary>",
            SYSTEM_INSTRUCTIONS,
        )
        self.assertIn(
            "<final_answer>Updated the tool documentation and ran the relevant tests.</final_answer>",
            SYSTEM_INSTRUCTIONS,
        )
        old_summary_tag = "<" + "th" + "ink" + ">"
        self.assertNotIn(old_summary_tag, SYSTEM_INSTRUCTIONS)

    def test_system_prompt_documents_tool_calls_and_observations(self) -> None:
        for field in ["name", "ok", "output", "error", "metadata"]:
            self.assertIn(field, SYSTEM_INSTRUCTIONS)

        expected_tool_details = {
            "read_file": ['{"path":"relative/path"}', "redacted file contents"],
            "write_file": ['{"path":"relative/path","content":"..."}', "written path and byte count"],
            "edit_file": [
                '{"path":"relative/path","old_text":"...","new_text":"..."}',
                "old_text must match exactly once",
            ],
            "list_files": ["{}", "newline-separated relative paths"],
            "grep_search": ['{"pattern":"text"}', "path:line: text"],
            "run_shell": ['{"command":"shell command"}', "stdout/stderr"],
        }
        for tool, details in expected_tool_details.items():
            self.assertIn(tool, SYSTEM_INSTRUCTIONS)
            for detail in details:
                self.assertIn(detail, SYSTEM_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
