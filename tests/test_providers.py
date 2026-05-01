from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from code_agent.models import WorkspaceContext
from code_agent.providers import OpenAIResponsesProvider


class FakeResponse:
    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"output_text": "ok"}'


class ProviderTests(unittest.TestCase):
    def test_openai_provider_uses_code_agent_env_for_request_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            (root / ".env").write_text(
                "DASHSCOPE_API_KEY=workspace-key\n"
                "DASHSCOPE_BASE_URL=https://workspace.example.test/v1\n"
                "DASHSCOPE_MODEL=workspace-model\n",
                encoding="utf-8",
            )
            config_env = Path(tmp) / "code-agent.env"
            config_env.write_text(
                "DASHSCOPE_API_KEY=file-key\n"
                "DASHSCOPE_BASE_URL=https://dashscope.example.test/v1\n"
                "DASHSCOPE_MODEL=qwen-from-file\n",
                encoding="utf-8",
            )
            context = WorkspaceContext(root=root, prompt="task", git_status="", files=[])
            captured: dict[str, object] = {}

            def fake_urlopen(request: urllib.request.Request, timeout: int) -> FakeResponse:
                captured["url"] = request.full_url
                captured["authorization"] = request.get_header("Authorization")
                data = request.data
                assert isinstance(data, bytes)
                captured["payload"] = json.loads(data.decode("utf-8"))
                captured["timeout"] = timeout
                return FakeResponse()

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
                patch("urllib.request.urlopen", side_effect=fake_urlopen),
            ):
                response = OpenAIResponsesProvider(system_instructions="dynamic instructions").complete(
                    "task",
                    context,
                    model="model-from-argument",
                )

            payload = captured["payload"]
            assert isinstance(payload, dict)
            self.assertEqual(response, "ok")
            self.assertEqual(payload["model"], "qwen-from-file")
            self.assertEqual(captured["url"], "https://dashscope.example.test/v1/responses")
            self.assertEqual(captured["authorization"], "Bearer file-key")
            self.assertEqual(captured["timeout"], 120)
            self.assertEqual(payload["instructions"], "dynamic instructions")
            content = payload["input"][0]["content"][0]
            self.assertEqual(content["type"], "input_text")
            self.assertEqual(content["text"], "task")
            self.assertNotIn("User task:", content["text"])
            self.assertNotIn("Workspace context:", content["text"])

    def test_openai_provider_ignores_workspace_env_when_config_is_missing_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            (root / ".env").write_text(
                "DASHSCOPE_API_KEY=workspace-key\n"
                "DASHSCOPE_MODEL=workspace-model\n",
                encoding="utf-8",
            )
            config_env = Path(tmp) / "code-agent.env"
            config_env.write_text("DASHSCOPE_MODEL=qwen-from-file\n", encoding="utf-8")
            context = WorkspaceContext(root=root, prompt="task", git_status="", files=[])

            with patch.dict(os.environ, {"CODE_AGENT_ENV_FILE": str(config_env)}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "API_KEY"):
                    OpenAIResponsesProvider().complete(
                        "task",
                        context,
                        model="model-from-argument",
                    )


if __name__ == "__main__":
    unittest.main()
