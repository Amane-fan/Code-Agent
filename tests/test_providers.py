from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from code_agent.models import WorkspaceContext
from code_agent.providers import OpenAICompatibleChatProvider, _extract_langchain_message_text


class ProviderTests(unittest.TestCase):
    def test_openai_provider_uses_langchain_chat_model_with_code_agent_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            (root / ".env").write_text(
                "API_KEY=workspace-key\n"
                "BASE_URL=https://workspace.example.test/v1\n"
                "MODEL=workspace-model\n",
                encoding="utf-8",
            )
            config_env = Path(tmp) / "code-agent.env"
            config_env.write_text(
                "API_KEY=file-key\n"
                "BASE_URL=https://dashscope.example.test/v1\n"
                "MODEL=qwen-from-file\n",
                encoding="utf-8",
            )
            context = WorkspaceContext(root=root, prompt="task", git_status="", files=[])

            with (
                patch.dict(
                    os.environ,
                    {
                        "CODE_AGENT_ENV_FILE": str(config_env),
                        "OPENAI_API_KEY": "shell-key",
                        "OPENAI_BASE_URL": "https://openai.example.test/v1",
                        "OPENAI_MODEL": "model-from-shell",
                    },
                    clear=True,
                ),
                patch("code_agent.providers.ChatOpenAI") as chat_openai,
            ):
                chat_openai.return_value.invoke.return_value = SimpleNamespace(content="ok")
                response = OpenAICompatibleChatProvider(system_instructions="dynamic instructions").complete(
                    "task",
                    context,
                    model="model-from-argument",
            )

            self.assertEqual(response, "ok")
            call_kwargs = chat_openai.call_args.kwargs
            self.assertEqual(call_kwargs["model"], "qwen-from-file")
            self.assertEqual(call_kwargs["api_key"].get_secret_value(), "file-key")
            self.assertEqual(call_kwargs["base_url"], "https://dashscope.example.test/v1")
            self.assertEqual(call_kwargs["timeout"], 120)
            self.assertEqual(call_kwargs["max_retries"], 0)
            chat_openai.return_value.invoke.assert_called_once_with(
                [("system", "dynamic instructions"), ("human", "task")]
            )

    def test_openai_provider_strips_chat_completions_endpoint_for_langchain_base_url(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            config_env = Path(tmp) / "code-agent.env"
            config_env.write_text(
                "API_KEY=file-key\n"
                "BASE_URL=https://compatible.example.test/v1/chat/completions\n"
                "MODEL=compatible-model\n",
                encoding="utf-8",
            )
            context = WorkspaceContext(root=root, prompt="task", git_status="", files=[])

            with (
                patch.dict(os.environ, {"CODE_AGENT_ENV_FILE": str(config_env)}, clear=True),
                patch("code_agent.providers.ChatOpenAI") as chat_openai,
            ):
                chat_openai.return_value.invoke.return_value = SimpleNamespace(content="ok")
                OpenAICompatibleChatProvider().complete("task", context, model="model-from-argument")

            self.assertEqual(chat_openai.call_args.kwargs["base_url"], "https://compatible.example.test/v1")

    def test_openai_provider_ignores_workspace_env_when_config_is_missing_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            (root / ".env").write_text(
                "API_KEY=workspace-key\n"
                "MODEL=workspace-model\n",
                encoding="utf-8",
            )
            config_env = Path(tmp) / "code-agent.env"
            config_env.write_text("MODEL=qwen-from-file\n", encoding="utf-8")
            context = WorkspaceContext(root=root, prompt="task", git_status="", files=[])

            with (
                patch.dict(os.environ, {"CODE_AGENT_ENV_FILE": str(config_env)}, clear=True),
                patch("code_agent.providers.ChatOpenAI") as chat_openai,
            ):
                with self.assertRaisesRegex(RuntimeError, "API_KEY"):
                    OpenAICompatibleChatProvider().complete(
                        "task",
                        context,
                        model="model-from-argument",
                    )
                chat_openai.assert_not_called()

    def test_extract_langchain_message_text_reads_string_content(self) -> None:
        message = SimpleNamespace(content="plain response")

        self.assertEqual(_extract_langchain_message_text(message), "plain response")

    def test_extract_langchain_message_text_reads_text_content_blocks(self) -> None:
        message = SimpleNamespace(
            content=[
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ]
        )

        self.assertEqual(_extract_langchain_message_text(message), "first\nsecond")


if __name__ == "__main__":
    unittest.main()
