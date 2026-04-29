from __future__ import annotations

import json
import os
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from code_agent.models import RepoContext
from code_agent.providers import OpenAIResponsesProvider


class FakeResponse:
    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"output_text": "ok"}'


class ProviderTests(unittest.TestCase):
    def test_openai_provider_uses_repo_env_for_request_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                "DASHSCOPE_API_KEY=file-key\n"
                "DASHSCOPE_BASE_URL=https://dashscope.example.test/v1\n"
                "DASHSCOPE_MODEL=qwen-from-file\n",
                encoding="utf-8",
            )
            context = RepoContext(root=root, prompt="task", git_status="", files=[])
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
                        "OPENAI_API_KEY": "shell-key",
                        "OPENAI_BASE_URL": "https://openai.example.test/v1",
                        "OPENAI_MODEL": "model-from-shell",
                    },
                    clear=True,
                ),
                patch("urllib.request.urlopen", side_effect=fake_urlopen),
            ):
                response = OpenAIResponsesProvider().complete(
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

    def test_openai_provider_requires_model_in_repo_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("DASHSCOPE_API_KEY=file-key\n", encoding="utf-8")
            context = RepoContext(root=root, prompt="task", git_status="", files=[])

            with patch.dict(os.environ, {"OPENAI_MODEL": "model-from-shell"}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "MODEL.*\\.env"):
                    OpenAIResponsesProvider().complete(
                        "task",
                        context,
                        model="model-from-argument",
                    )


if __name__ == "__main__":
    unittest.main()
