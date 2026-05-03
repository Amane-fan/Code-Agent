from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_agent.skills import SkillRegistry
from code_agent.tools import create_workspace_tool_registry


def _write_skill(skills_root: Path, dirname: str, content: str) -> Path:
    skill_dir = skills_root / dirname
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


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

    def test_load_skill_resources_tool_loads_supporting_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            skills_root = Path(tmp) / "skills"
            skill_dir = _write_skill(
                skills_root,
                "python",
                "---\n"
                "name: python\n"
                "description: Use when editing Python code.\n"
                "---\n\n"
                "Full skill instructions.\n",
            )
            (skill_dir / "references").mkdir()
            (skill_dir / "resources").mkdir()
            (skill_dir / "references" / "guide.md").write_text("Guide text.\n", encoding="utf-8")
            (skill_dir / "resources" / "template.txt").write_text(
                "api_key=abcdefghijklmnop\n",
                encoding="utf-8",
            )
            skill_registry = SkillRegistry.from_directory(skills_root)
            tool_registry = create_workspace_tool_registry(root, skill_registry=skill_registry)

            loaded = tool_registry.execute(
                "load_skill_resources",
                {
                    "name": "python",
                    "paths": ["references/guide.md", "resources/template.txt"],
                },
            )

            self.assertTrue(loaded.ok)
            self.assertEqual(loaded.name, "load_skill_resources")
            self.assertIn("--- references/guide.md ---\nGuide text.", loaded.output)
            self.assertIn("--- resources/template.txt ---", loaded.output)
            self.assertIn("api_key=[REDACTED]", loaded.output)

    def test_load_skill_resources_tool_rejects_invalid_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            skills_root = Path(tmp) / "skills"
            skill_dir = _write_skill(
                skills_root,
                "python",
                "---\n"
                "name: python\n"
                "description: Use when editing Python code.\n"
                "---\n\n"
                "Full skill instructions.\n",
            )
            (skill_dir / "references").mkdir()
            (skill_dir / "resources").mkdir()
            (skill_dir / "references" / "guide.md").write_text("Guide text.\n", encoding="utf-8")
            (skill_dir / "root.txt").write_text("Root file.\n", encoding="utf-8")
            skill_registry = SkillRegistry.from_directory(skills_root)
            tool_registry = create_workspace_tool_registry(root, skill_registry=skill_registry)

            invalid_cases = [
                ("missing", ["references/guide.md"], "unknown skill"),
                ("python", ["/tmp/guide.md"], "must be relative"),
                ("python", ["references/../root.txt"], "may not contain '..'"),
                ("python", ["root.txt"], "must start with references/ or resources/"),
                ("python", ["references"], "must start with references/ or resources/"),
                ("python", ["references/missing.md"], "does not exist"),
                ("python", ["resources/"], "directory"),
                ("python", ["SKILL.md"], "SKILL.md"),
                ("python", ["references/SKILL.md"], "SKILL.md"),
            ]
            for name, paths, expected_error in invalid_cases:
                with self.subTest(name=name, paths=paths):
                    result = tool_registry.execute(
                        "load_skill_resources",
                        {"name": name, "paths": paths},
                    )
                    self.assertFalse(result.ok)
                    self.assertEqual(result.output, "")
                    self.assertIn(expected_error, result.error)

    def test_load_skill_tool_is_not_registered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            tool_registry = create_workspace_tool_registry(root, skill_registry=SkillRegistry.empty())

            result = tool_registry.execute("load_skill", {"name": "python"})

            self.assertFalse(result.ok)
            self.assertIn("unknown tool", result.error)


if __name__ == "__main__":
    unittest.main()
