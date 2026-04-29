from __future__ import annotations

import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from code_agent.cli import main


class CliTests(unittest.TestCase):
    def test_tool_run_keeps_top_level_command_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_dummy.py").write_text(
                "import unittest\n\n"
                "class DummyTest(unittest.TestCase):\n"
                "    def test_ok(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                exit_code = main(
                    [
                        "tool",
                        "run",
                        "python -m unittest discover -s tests",
                        "--repo",
                        str(root),
                    ]
                )
            self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
