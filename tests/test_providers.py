from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool

from code_agent.models import ModelCompletion, ModelToolCall, TokenUsage
from code_agent.providers import (
    OpenAICompatibleChatProvider,
    _ReasoningContentChatOpenAI,
    _extract_langchain_message_text,
    _extract_langchain_reasoning_content,
    _extract_langchain_token_usage,
    _extract_langchain_tool_calls,
)


class ProviderTests(unittest.TestCase):
    def test_openai_provider_uses_langchain_messages_and_binds_tools(self) -> None:
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
            messages = [SystemMessage(content="dynamic instructions"), HumanMessage(content="task")]

            @tool("echo")
            def echo(message: str) -> str:
                """Echo a message."""

                return message

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
                patch("code_agent.providers._ReasoningContentChatOpenAI") as chat_openai,
            ):
                bound = Mock()
                bound.invoke.return_value = SimpleNamespace(
                    content="ok",
                    usage_metadata={
                        "input_tokens": 11,
                        "output_tokens": 7,
                        "total_tokens": 18,
                    },
                    tool_calls=[
                        {"id": "call_echo", "name": "echo", "args": {"message": "hi"}}
                    ],
                    additional_kwargs={"reasoning_content": "thinking trace"},
                )
                chat_openai.return_value.bind_tools.return_value = bound

                response = OpenAICompatibleChatProvider().complete(
                    messages,
                    model="model-from-argument",
                    tools=[echo],
                )

            self.assertEqual(
                response,
                ModelCompletion(
                    text="ok",
                    usage=TokenUsage(
                        prompt_tokens=11,
                        completion_tokens=7,
                        total_tokens=18,
                    ),
                    tool_calls=[
                        ModelToolCall(id="call_echo", name="echo", args={"message": "hi"})
                    ],
                    reasoning_content="thinking trace",
                ),
            )
            call_kwargs = chat_openai.call_args.kwargs
            self.assertEqual(call_kwargs["model"], "qwen-from-file")
            self.assertEqual(call_kwargs["api_key"].get_secret_value(), "file-key")
            self.assertEqual(call_kwargs["base_url"], "https://dashscope.example.test/v1")
            self.assertEqual(call_kwargs["timeout"], 120)
            self.assertEqual(call_kwargs["max_retries"], 0)
            chat_openai.return_value.bind_tools.assert_called_once_with([echo])
            bound.invoke.assert_called_once_with(messages)

    def test_openai_provider_invokes_without_binding_when_no_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_env = Path(tmp) / "code-agent.env"
            config_env.write_text("API_KEY=file-key\nMODEL=qwen-from-file\n", encoding="utf-8")
            messages = [HumanMessage(content="task")]

            with (
                patch.dict(os.environ, {"CODE_AGENT_ENV_FILE": str(config_env)}, clear=True),
                patch("code_agent.providers._ReasoningContentChatOpenAI") as chat_openai,
            ):
                chat_openai.return_value.invoke.return_value = SimpleNamespace(content="ok")
                response = OpenAICompatibleChatProvider().complete(
                    messages,
                    model="model-from-argument",
                )

            chat_openai.return_value.bind_tools.assert_not_called()
            chat_openai.return_value.invoke.assert_called_once_with(messages)
            self.assertEqual(response, ModelCompletion(text="ok"))

    def test_openai_provider_strips_chat_completions_endpoint_for_langchain_base_url(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_env = Path(tmp) / "code-agent.env"
            config_env.write_text(
                "API_KEY=file-key\n"
                "BASE_URL=https://compatible.example.test/v1/chat/completions\n"
                "MODEL=compatible-model\n",
                encoding="utf-8",
            )

            with (
                patch.dict(os.environ, {"CODE_AGENT_ENV_FILE": str(config_env)}, clear=True),
                patch("code_agent.providers._ReasoningContentChatOpenAI") as chat_openai,
            ):
                chat_openai.return_value.invoke.return_value = SimpleNamespace(content="ok")
                response = OpenAICompatibleChatProvider().complete(
                    [HumanMessage(content="task")],
                    model="model-from-argument",
                )

            self.assertEqual(
                chat_openai.call_args.kwargs["base_url"],
                "https://compatible.example.test/v1",
            )
            self.assertEqual(response, ModelCompletion(text="ok"))

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

            with (
                patch.dict(os.environ, {"CODE_AGENT_ENV_FILE": str(config_env)}, clear=True),
                patch("code_agent.providers._ReasoningContentChatOpenAI") as chat_openai,
            ):
                with self.assertRaisesRegex(RuntimeError, "API_KEY"):
                    OpenAICompatibleChatProvider().complete(
                        [HumanMessage(content="task")],
                        model="model-from-argument",
                )
                chat_openai.assert_not_called()

    def test_reasoning_chat_openai_preserves_response_reasoning_content(self) -> None:
        llm = _ReasoningContentChatOpenAI(
            model="compatible-model",
            api_key="test-key",
            base_url="https://compatible.example.test/v1",
        )

        chat_result = llm._create_chat_result(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "type": "function",
                                    "id": "call_list",
                                    "function": {
                                        "name": "list_files",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                            "reasoning_content": "thinking trace",
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 4,
                    "completion_tokens": 3,
                    "total_tokens": 7,
                },
                "model": "compatible-model",
            }
        )

        message = chat_result.generations[0].message
        self.assertIsInstance(message, AIMessage)
        self.assertEqual(
            message.additional_kwargs["reasoning_content"],
            "thinking trace",
        )
        self.assertEqual(_extract_langchain_reasoning_content(message), "thinking trace")

    def test_reasoning_chat_openai_replays_reasoning_content_in_request_payload(self) -> None:
        llm = _ReasoningContentChatOpenAI(
            model="compatible-model",
            api_key="test-key",
            base_url="https://compatible.example.test/v1",
        )
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "id": "call_list",
                    "name": "list_files",
                    "args": {},
                }
            ],
            additional_kwargs={"reasoning_content": "thinking trace"},
        )

        payload = llm._get_request_payload([message])

        self.assertEqual(
            payload["messages"][0]["reasoning_content"],
            "thinking trace",
        )

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

    def test_extract_langchain_tool_calls_reads_langchain_tool_call_dicts(self) -> None:
        message = SimpleNamespace(
            tool_calls=[
                {"id": "call_1", "name": "read_file", "args": {"path": "README.md"}},
                {"id": "call_2", "name": "list_files", "args": "{}"},
            ]
        )

        self.assertEqual(
            _extract_langchain_tool_calls(message),
            [
                ModelToolCall(id="call_1", name="read_file", args={"path": "README.md"}),
                ModelToolCall(id="call_2", name="list_files", args={}),
            ],
        )

    def test_extract_langchain_reasoning_content_reads_additional_kwargs(self) -> None:
        message = SimpleNamespace(
            additional_kwargs={"reasoning_content": "thinking trace"}
        )

        self.assertEqual(_extract_langchain_reasoning_content(message), "thinking trace")

    def test_extract_langchain_reasoning_content_reads_nested_reasoning(self) -> None:
        message = SimpleNamespace(additional_kwargs={"reasoning": {"content": "nested trace"}})

        self.assertEqual(_extract_langchain_reasoning_content(message), "nested trace")

    def test_extract_langchain_reasoning_content_reads_reasoning_blocks(self) -> None:
        message = SimpleNamespace(
            content=[
                {"type": "reasoning", "text": "block trace"},
                {"type": "text", "text": "visible answer"},
            ]
        )

        self.assertEqual(_extract_langchain_reasoning_content(message), "block trace")

    def test_extract_langchain_token_usage_reads_response_metadata(self) -> None:
        message = SimpleNamespace(
            response_metadata={
                "token_usage": {
                    "prompt_tokens": 13,
                    "completion_tokens": 5,
                    "total_tokens": 18,
                }
            }
        )

        self.assertEqual(
            _extract_langchain_token_usage(message),
            TokenUsage(prompt_tokens=13, completion_tokens=5, total_tokens=18),
        )

    def test_extract_langchain_token_usage_returns_none_when_missing(self) -> None:
        self.assertIsNone(_extract_langchain_token_usage(SimpleNamespace(content="ok")))


if __name__ == "__main__":
    unittest.main()
