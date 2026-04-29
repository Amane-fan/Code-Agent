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

    def __init__(self, response: str = "default provider response") -> None:
        self.response = response

    def complete(self, prompt: str, context: WorkspaceContext, *, model: str) -> str:
        return self.response


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)


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
            with (
                patch("builtins.input", side_effect=["总结项目", "/quit"]),
                patch("code_agent.graph.make_provider", return_value=FakeProvider()) as make_provider,
                redirect_stdout(stdout),
                redirect_stderr(StringIO()),
            ):
                exit_code = main(["--workspace", str(root), "--no-session"])

            self.assertEqual(exit_code, 0)
            make_provider.assert_called_once_with("openai")
            self.assertIn("default provider response", stdout.getvalue())

    def test_interactive_patch_can_be_rejected_after_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / "app.py").write_text("old\n", encoding="utf-8")

            stdout = StringIO()
            with (
                patch("builtins.input", side_effect=["更新 app", "n", "/exit"]),
                patch(
                    "code_agent.graph.make_provider",
                    return_value=FakeProvider(_replace_patch("old", "new")),
                ),
                redirect_stdout(stdout),
                redirect_stderr(StringIO()),
            ):
                exit_code = main(["--workspace", str(root), "--no-session"])

            self.assertEqual(exit_code, 0)
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "old\n")
            self.assertIn("Patch check: ok", stdout.getvalue())
            self.assertIn("Patch not applied.", stdout.getvalue())

    def test_interactive_patch_can_be_applied_after_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / "app.py").write_text("old\n", encoding="utf-8")

            stdout = StringIO()
            with (
                patch("builtins.input", side_effect=["更新 app", "y", "/exit"]),
                patch(
                    "code_agent.graph.make_provider",
                    return_value=FakeProvider(_replace_patch("old", "new")),
                ),
                redirect_stdout(stdout),
                redirect_stderr(StringIO()),
            ):
                exit_code = main(["--workspace", str(root), "--no-session"])

            self.assertEqual(exit_code, 0)
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "new\n")
            self.assertIn("Patch applied.", stdout.getvalue())

    def test_interactive_patch_check_failure_does_not_prompt_or_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / "app.py").write_text("actual\n", encoding="utf-8")

            stdout = StringIO()
            with (
                patch("builtins.input", side_effect=["更新 app", "/exit"]),
                patch(
                    "code_agent.graph.make_provider",
                    return_value=FakeProvider(_replace_patch("missing", "new")),
                ),
                redirect_stdout(stdout),
                redirect_stderr(StringIO()),
            ):
                exit_code = main(["--workspace", str(root), "--no-session"])

            self.assertEqual(exit_code, 0)
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "actual\n")
            self.assertIn("Patch check: failed", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
