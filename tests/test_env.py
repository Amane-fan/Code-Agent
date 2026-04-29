from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent.config import AgentConfig
from code_agent.env import load_env_file
from code_agent.providers import _responses_api_url


class EnvTests(unittest.TestCase):
    def test_load_env_file_reads_simple_values_without_overriding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(
                "CODE_AGENT_TEST_EXISTING=from-file\n"
                "CODE_AGENT_TEST_QUOTED='quoted value'\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"CODE_AGENT_TEST_EXISTING": "from-env"}):
                load_env_file(env_path)

                self.assertEqual(os.environ["CODE_AGENT_TEST_EXISTING"], "from-env")
                self.assertEqual(os.environ["CODE_AGENT_TEST_QUOTED"], "quoted value")

    def test_agent_config_loads_repo_env_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("DASHSCOPE_MODEL=qwen3.6-plus\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                config = AgentConfig(repo_path=root)

            self.assertEqual(config.model, "qwen3.6-plus")

    def test_agent_config_prefers_repo_env_model_over_process_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("DASHSCOPE_MODEL=qwen-from-file\n", encoding="utf-8")

            with patch.dict(os.environ, {"OPENAI_MODEL": "model-from-shell"}, clear=True):
                config = AgentConfig(repo_path=root)

            self.assertEqual(config.model, "qwen-from-file")

    def test_agent_config_defaults_to_openai_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = AgentConfig(repo_path=Path(tmp))

        self.assertEqual(config.provider, "openai")

    def test_responses_url_is_derived_from_base_url(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DASHSCOPE_BASE_URL": (
                    "https://dashscope.aliyuncs.com/api/v2/apps/protocols/"
                    "compatible-mode/v1"
                )
            },
            clear=True,
        ):
            self.assertEqual(
                _responses_api_url(),
                "https://dashscope.aliyuncs.com/api/v2/apps/protocols/"
                "compatible-mode/v1/responses",
            )


if __name__ == "__main__":
    unittest.main()
