from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_agent.skills import SkillRegistry
from code_agent.tools import create_workspace_tool_registry


def _write_skill(skills_root: Path, dirname: str, content: str) -> None:
    skill_dir = skills_root / dirname
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


class SkillRegistryTests(unittest.TestCase):
    def test_loads_metadata_without_body_and_loads_body_on_demand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skills_root = Path(tmp) / "skills"
            _write_skill(
                skills_root,
                "python",
                "---\n"
                "name: python\n"
                "description: Use when editing Python code.\n"
                "---\n\n"
                "# Python Skill\n\n"
                "Full skill body that should only load on demand.\n",
            )

            registry = SkillRegistry.from_directory(skills_root)

            metadata = registry.list_metadata()
            self.assertEqual(len(metadata), 1)
            self.assertEqual(metadata[0].name, "python")
            self.assertEqual(metadata[0].description, "Use when editing Python code.")
            self.assertNotIn("Full skill body", metadata[0].description)
            self.assertIn("Full skill body", registry.load("python").content)

    def test_missing_skills_directory_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = SkillRegistry.from_directory(Path(tmp) / "missing")

            self.assertEqual(registry.list_metadata(), [])

    def test_rejects_duplicate_skill_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skills_root = Path(tmp) / "skills"
            for dirname in ["one", "two"]:
                _write_skill(
                    skills_root,
                    dirname,
                    "---\n"
                    "name: duplicate\n"
                    "description: Repeated name.\n"
                    "---\n\n"
                    "Body.\n",
                )

            with self.assertRaisesRegex(ValueError, "duplicate skill name"):
                SkillRegistry.from_directory(skills_root)

    def test_rejects_missing_required_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skills_root = Path(tmp) / "skills"
            _write_skill(
                skills_root,
                "broken",
                "---\n"
                "name: broken\n"
                "---\n\n"
                "Body.\n",
            )

            with self.assertRaisesRegex(ValueError, "missing required metadata"):
                SkillRegistry.from_directory(skills_root)

    def test_load_skill_tool_returns_full_skill_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            skills_root = Path(tmp) / "skills"
            _write_skill(
                skills_root,
                "python",
                "---\n"
                "name: python\n"
                "description: Use when editing Python code.\n"
                "---\n\n"
                "Full skill instructions.\n",
            )
            skill_registry = SkillRegistry.from_directory(skills_root)
            tool_registry = create_workspace_tool_registry(root, skill_registry=skill_registry)

            loaded = tool_registry.execute("load_skill", {"name": "python"})
            missing = tool_registry.execute("load_skill", {"name": "missing"})

            self.assertTrue(loaded.ok)
            self.assertEqual(loaded.name, "load_skill")
            self.assertIn("Full skill instructions.", loaded.output)
            self.assertFalse(missing.ok)
            self.assertIn("unknown skill", missing.error)


if __name__ == "__main__":
    unittest.main()
