from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_agent.config import AgentConfig
from code_agent.env import load_env_file
import code_agent.providers as providers


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

    def test_agent_config_loads_code_agent_env_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            config_env = Path(tmp) / "code-agent.env"
            config_env.write_text("MODEL=qwen3.6-plus\n", encoding="utf-8")

            with patch.dict(os.environ, {"CODE_AGENT_ENV_FILE": str(config_env)}, clear=True):
                config = AgentConfig(workspace_path=root)

            self.assertEqual(config.model, "qwen3.6-plus")

    def test_agent_config_ignores_workspace_env_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            (root / ".env").write_text("MODEL=workspace-model\n", encoding="utf-8")
            config_env = Path(tmp) / "code-agent.env"
            config_env.write_text("MODEL=code-agent-model\n", encoding="utf-8")

            with patch.dict(
                os.environ,
                {
                    "CODE_AGENT_ENV_FILE": str(config_env),
                    "OPENAI_MODEL": "model-from-shell",
                },
                clear=True,
            ):
                config = AgentConfig(workspace_path=root)

            self.assertEqual(config.model, "code-agent-model")

    def test_agent_config_defaults_to_openai_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {"CODE_AGENT_ENV_FILE": str(Path(tmp) / "missing.env")},
                clear=True,
            ):
                config = AgentConfig(workspace_path=Path(tmp))

        self.assertEqual(config.provider, "openai")

    def test_langchain_base_url_is_derived_from_base_url(self) -> None:
        with patch.dict(
            os.environ,
            {
                "BASE_URL": (
                    "https://dashscope.aliyuncs.com/api/v2/apps/protocols/"
                    "compatible-mode/v1"
                ),
                "CODE_AGENT_ENV_FILE": "/tmp/code-agent-missing-env-for-test",
            },
            clear=True,
        ):
            self.assertEqual(
                providers._langchain_base_url(),
                "https://dashscope.aliyuncs.com/api/v2/apps/protocols/"
                "compatible-mode/v1",
            )

    def test_langchain_base_url_accepts_full_chat_completions_endpoint(self) -> None:
        with patch.dict(
            os.environ,
            {
                "BASE_URL": "https://compatible.example.test/v1/chat/completions",
                "CODE_AGENT_ENV_FILE": "/tmp/code-agent-missing-env-for-test",
            },
            clear=True,
        ):
            self.assertEqual(
                providers._langchain_base_url(),
                "https://compatible.example.test/v1",
            )


if __name__ == "__main__":
    unittest.main()
