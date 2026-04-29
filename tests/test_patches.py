from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from code_agent.patches import PatchTool, extract_unified_diff


class PatchTests(unittest.TestCase):
    def test_extract_unified_diff_from_fenced_block(self) -> None:
        text = """Plan

```diff
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-old
+new
```
"""
        patch = extract_unified_diff(text)
        self.assertIsNotNone(patch)
        assert patch is not None
        self.assertTrue(patch.startswith("diff --git a/app.py b/app.py"))

    def test_patch_tool_applies_git_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            (root / "app.py").write_text("old\n", encoding="utf-8")
            patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-old
+new
"""

            tool = PatchTool(root)
            self.assertTrue(tool.check(patch).ok)
            self.assertTrue(tool.apply(patch).ok)
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "new\n")


if __name__ == "__main__":
    unittest.main()
