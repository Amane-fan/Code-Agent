from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_agent.context import collect_repo_context


class ContextTests(unittest.TestCase):
    def test_collect_context_ranks_prompt_terms_and_skips_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "billing.py").write_text(
                "def invoice_total():\n    return 42\n",
                encoding="utf-8",
            )
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            (root / ".env").write_text("OPENAI_API_KEY=secret-value\n", encoding="utf-8")

            context = collect_repo_context(
                root,
                "fix billing invoice total",
                max_files=5,
                max_file_bytes=10_000,
                max_context_chars=50_000,
            )

            paths = [file.path for file in context.files]
            self.assertEqual(paths[0], "billing.py")
            self.assertNotIn(".env", paths)


if __name__ == "__main__":
    unittest.main()
