from __future__ import annotations

import unittest

from code_agent.providers import SYSTEM_INSTRUCTIONS


class PromptTests(unittest.TestCase):
    def test_system_prompt_is_written_in_chinese(self) -> None:
        self.assertIn("你是一个谨慎的终端编程 Agent", SYSTEM_INSTRUCTIONS)
        self.assertIn("每一轮必须输出以下两种格式之一", SYSTEM_INSTRUCTIONS)
        self.assertIn("不要包含密钥", SYSTEM_INSTRUCTIONS)
        self.assertIn("read_file", SYSTEM_INSTRUCTIONS)
        self.assertIn("<action>", SYSTEM_INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
