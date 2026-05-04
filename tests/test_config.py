import os

from terminal_code_agent.config import load_settings


def test_load_settings_exports_provider_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MODEL_NAME=openai:deepseek-chat\n"
        "MODEL_BASE_URL=https://api.deepseek.com/v1\n"
        "OPENAI_API_KEY=test-key\n",
        encoding="utf-8",
    )

    settings = load_settings(env_file)

    assert settings.model_name == "openai:deepseek-chat"
    assert settings.model_base_url == "https://api.deepseek.com/v1"
    assert os.environ["OPENAI_API_KEY"] == "test-key"


def test_load_settings_does_not_override_existing_api_key(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "shell-key")
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=file-key\n", encoding="utf-8")

    load_settings(env_file)

    assert os.environ["OPENAI_API_KEY"] == "shell-key"
