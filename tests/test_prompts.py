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
    def test_base_system_prompt_uses_json_event_protocol_not_xml(self) -> None:
        self.assertIn("You are a cautious terminal programming agent.", BASE_SYSTEM_INSTRUCTIONS)
        self.assertIn('"type": "final_answer"', BASE_SYSTEM_INSTRUCTIONS)
        self.assertIn('"type": "summary"', BASE_SYSTEM_INSTRUCTIONS)
        self.assertIn("native tool-calling interface", BASE_SYSTEM_INSTRUCTIONS)
        self.assertNotIn("<action>", BASE_SYSTEM_INSTRUCTIONS)
        self.assertNotIn("<final_answer>", BASE_SYSTEM_INSTRUCTIONS)
        self.assertNotIn("<summary>", BASE_SYSTEM_INSTRUCTIONS)

    def test_base_system_prompt_does_not_hardcode_tool_catalog(self) -> None:
        self.assertNotIn("- write_file:", BASE_SYSTEM_INSTRUCTIONS)
        self.assertIn("Available bound tools for this run:", BASE_SYSTEM_INSTRUCTIONS)

    def test_dynamic_system_prompt_replaces_placeholders_and_documents_json_schema(self) -> None:
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
            tool_registry = create_workspace_tool_registry(root, skill_registry=SkillRegistry.empty())

            system_instructions = build_system_instructions(
                tool_registry=tool_registry,
                skill_registry=skill_registry,
                workspace_root=root,
            )

        for placeholder in [
            "{workspace_root}",
            "{skill_catalog}",
            "{loaded_skills}",
            "{event_schema}",
        ]:
            self.assertNotIn(placeholder, system_instructions)
        for field in ["role", "type", "content", "final_answer"]:
            self.assertIn(field, system_instructions)

        for tool in [
            "read_file",
            "write_file",
            "edit_file",
            "list_files",
            "grep_search",
            "run_shell",
            "load_skill_resources",
        ]:
            self.assertIn(tool, system_instructions)

        self.assertIn('"name": "python"', system_instructions)
        self.assertIn('"description": "Use when editing Python code."', system_instructions)
        self.assertNotIn("Full skill body should not be in startup context.", system_instructions)
        self.assertIn(str(root.resolve()), system_instructions)
        self.assertNotIn("<loaded_skills>", system_instructions)
        self.assertNotIn("<skills>", system_instructions)

    def test_dynamic_system_prompt_injects_selected_skill_body(self) -> None:
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
                "Full selected skill body.\n",
                encoding="utf-8",
            )
            skill_registry = SkillRegistry.from_directory(skills_root)
            tool_registry = create_workspace_tool_registry(
                root,
                skill_registry=SkillRegistry.from_loaded([skill_registry.load("python")]),
            )

            system_instructions = build_system_instructions(
                tool_registry=tool_registry,
                skill_registry=skill_registry,
                loaded_skills=[skill_registry.load("python")],
                workspace_root=root,
            )

        self.assertIn("Loaded skills for this task:", system_instructions)
        self.assertIn("Full selected skill body.", system_instructions)
        self.assertIn(str(skill_dir / "SKILL.md"), system_instructions)

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
