import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

from terminal_code_agent.config import Settings
from terminal_code_agent.llm import DeepSeekThinkingChatOpenAI, build_chat_model


def test_build_chat_model_uses_chat_openai_with_bare_model_name(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    model = build_chat_model(
        Settings(
            model_name="deepseek-chat",
            model_base_url="https://api.deepseek.com/v1",
            model_temperature=0.2,
            model_max_tokens=1234,
            model_timeout_seconds=45,
        )
    )

    assert isinstance(model, ChatOpenAI)
    assert isinstance(model, DeepSeekThinkingChatOpenAI)
    assert model.model_name == "deepseek-chat"
    assert str(model.openai_api_base).rstrip("/") == "https://api.deepseek.com/v1"
    assert model.temperature == 0.2
    assert model.max_tokens == 1234
    assert model.request_timeout == 45


def test_build_chat_model_keeps_legacy_openai_prefix_working(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    model = build_chat_model(Settings(model_name="openai:gpt-test"))

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "gpt-test"


def test_build_chat_model_rejects_non_openai_provider_prefix(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with pytest.raises(ValueError, match="裸模型名"):
        build_chat_model(Settings(model_name="deepseek:deepseek-chat"))


def test_deepseek_reasoning_content_is_preserved_from_response(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    model = build_chat_model(Settings(model_name="deepseek-chat"))

    result = model._create_chat_result(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "需要先写文件。",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "write_file", "arguments": "{}"},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "model": "deepseek-chat",
        }
    )

    message = result.generations[0].message
    assert isinstance(message, AIMessage)
    assert message.additional_kwargs["reasoning_content"] == "需要先写文件。"


def test_deepseek_reasoning_content_is_sent_back_in_payload(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    model = build_chat_model(Settings(model_name="deepseek-chat"))

    payload = model._get_request_payload(
        [
            HumanMessage(content="写一个文件"),
            AIMessage(
                content="",
                additional_kwargs={"reasoning_content": "需要调用写文件工具。"},
                tool_calls=[{"id": "call_1", "name": "write_file", "args": {}}],
            ),
        ]
    )

    assert payload["messages"][1]["reasoning_content"] == "需要调用写文件工具。"
