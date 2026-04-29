from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent.agent import CodingAgent
from code_agent.config import AgentConfig
from code_agent.models import WorkspaceContext


class FakeProvider:
    name = "fake"

    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, prompt: str, context: WorkspaceContext, *, model: str) -> str:
        return self.response


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")


def _replace_patch(old: str, new: str) -> str:
    return f"""```diff
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-{old}
+{new}
```
"""


class GraphTests(unittest.TestCase):
    def test_offline_provider_runs_through_langgraph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)

            run = CodingAgent(AgentConfig(workspace_path=root, provider="offline")).run(
                "总结项目",
                save_session=False,
            )

            self.assertEqual(run.provider, "offline")
            self.assertIn("Offline planning mode", run.response_text)
            self.assertFalse(run.applied)

    def test_generated_patch_is_applied_after_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / "app.py").write_text("old\n", encoding="utf-8")

            with patch(
                "code_agent.graph.make_provider",
                return_value=FakeProvider(_replace_patch("old", "new")),
            ):
                run = CodingAgent(AgentConfig(workspace_path=root)).run(
                    "更新 app",
                    apply_patch=True,
                    save_session=False,
                )

            self.assertTrue(run.applied)
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "new\n")

    def test_patch_check_failure_stops_before_apply_and_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / "app.py").write_text("actual\n", encoding="utf-8")

            with patch(
                "code_agent.graph.make_provider",
                return_value=FakeProvider(_replace_patch("missing", "new")),
            ):
                run = CodingAgent(AgentConfig(workspace_path=root)).run(
                    "更新 app",
                    apply_patch=True,
                    run_tests=True,
                    save_session=False,
                )

            self.assertFalse(run.applied)
            self.assertIsNotNone(run.test_result)
            test_result = run.test_result
            assert test_result is not None
            self.assertEqual(test_result.name, "patch.check")
            self.assertFalse(test_result.ok)
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "actual\n")

    def test_applied_patch_can_run_detected_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / "app.py").write_text("old\n", encoding="utf-8")
            tests_dir = root / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_dummy.py").write_text(
                "import unittest\n\n"
                "class DummyTest(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )

            with patch(
                "code_agent.graph.make_provider",
                return_value=FakeProvider(_replace_patch("old", "new")),
            ):
                run = CodingAgent(AgentConfig(workspace_path=root)).run(
                    "更新 app",
                    apply_patch=True,
                    run_tests=True,
                    save_session=False,
                )

            self.assertTrue(run.applied)
            self.assertIsNotNone(run.test_result)
            test_result = run.test_result
            assert test_result is not None
            self.assertTrue(test_result.ok)
            self.assertEqual(test_result.name, "shell.run")


if __name__ == "__main__":
    unittest.main()
