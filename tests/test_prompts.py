from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_agent.agent import CodingAgent
from code_agent.config import AgentConfig
from code_agent.prompting import BASE_SYSTEM_INSTRUCTIONS, build_system_instructions
from code_agent.skills import SkillRegistry
from code_agent.tools import create_workspace_tool_registry


class PromptTests(unittest.TestCase):
    def test_system_prompt_keeps_english_protocol_examples(self) -> None:
        self.assertIn("You are a cautious terminal programming agent.", BASE_SYSTEM_INSTRUCTIONS)
        self.assertRegex(
            BASE_SYSTEM_INSTRUCTIONS,
            r"<summary>\s*Read README\.md to inspect the project overview\.\s*</summary>",
        )
        self.assertRegex(
            BASE_SYSTEM_INSTRUCTIONS,
            r"<action>\s*\{\"tool\":\"read_file\",\"args\":\{\"path\":\"README\.md\"\}\}\s*</action>",
        )
        self.assertRegex(
            BASE_SYSTEM_INSTRUCTIONS,
            r"<summary>\s*The requested change has been completed and verified\.\s*</summary>",
        )
        self.assertRegex(
            BASE_SYSTEM_INSTRUCTIONS,
            r"<final_answer>\s*Updated the tool documentation and ran the relevant tests\.\s*</final_answer>",
        )
        old_summary_tag = "<" + "th" + "ink" + ">"
        self.assertNotIn(old_summary_tag, BASE_SYSTEM_INSTRUCTIONS)

    def test_base_system_prompt_does_not_hardcode_tool_catalog(self) -> None:
        self.assertNotIn("Available tools:", BASE_SYSTEM_INSTRUCTIONS)
        self.assertNotIn("- write_file:", BASE_SYSTEM_INSTRUCTIONS)

    def test_dynamic_system_prompt_documents_tools_and_skill_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            skills_root = Path(tmp) / "skills"
            skill_dir = skills_root / "python"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: python\n"
                "description: Use when editing Python code.\n"
                "---\n\n"
                "Full skill body should not be in startup context.\n",
                encoding="utf-8",
            )
            skill_registry = SkillRegistry.from_directory(skills_root)
            tool_registry = create_workspace_tool_registry(root, skill_registry=skill_registry)

            system_instructions = build_system_instructions(
                tool_registry=tool_registry,
                skill_registry=skill_registry,
                workspace_root=root,
            )

        for field in ["name", "ok", "output", "error", "metadata"]:
            self.assertIn(field, system_instructions)

        expected_tool_details = {
            "read_file": ['"path"', '"required":["path"]', "redacted file contents"],
            "write_file": ['"content"', '"required":["path","content"]', "written path and byte count"],
            "edit_file": [
                '"old_text"',
                '"new_text"',
                "old_text must match exactly once",
            ],
            "list_files": ["{}", "newline-separated relative paths"],
            "grep_search": ['"pattern"', "path:line: text"],
            "run_shell": ['"command"', "stdout/stderr"],
            "load_skill": ['"name"', "full skill instructions"],
        }
        for tool, details in expected_tool_details.items():
            self.assertIn(tool, system_instructions)
            for detail in details:
                self.assertIn(detail, system_instructions)

        self.assertIn("<skills>", system_instructions)
        self.assertIn(
            "<skill>\n"
            "  <name>python</name>\n"
            "  <description>Use when editing Python code.</description>\n"
            "</skill>",
            system_instructions,
        )
        self.assertIn("</skills>", system_instructions)
        self.assertNotIn("- python: Use when editing Python code.", system_instructions)
        self.assertNotIn("Full skill body should not be in startup context.", system_instructions)
        self.assertIn("Target workspace:", system_instructions)
        self.assertIn(str(root.resolve()), system_instructions)

    def test_coding_agent_system_prompt_includes_workspace_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            agent = CodingAgent(
                AgentConfig(
                    workspace_path=root,
                    provider="offline",
                    session_root=Path(tmp) / "sessions",
                    skills_path=Path(tmp) / "skills",
                )
            )

            self.assertIn("Target workspace:", agent.system_instructions)
            self.assertIn(str(root.resolve()), agent.system_instructions)


if __name__ == "__main__":
    unittest.main()
