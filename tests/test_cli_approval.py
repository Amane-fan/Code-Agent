import json

from terminal_code_agent import cli
from terminal_code_agent.cli import (
    _format_call_arguments_markdown,
    ask_user_for_approval,
    configure_line_editor,
)


def test_approval_yes(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "y")

    result = ask_user_for_approval({"tool_calls": [], "risk": "test"})

    assert result["decision"] == "approved"


def test_approval_no(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _: "n")

    result = ask_user_for_approval({"tool_calls": [], "risk": "test"})

    assert result["decision"] == "rejected"


def test_approval_edit(monkeypatch) -> None:
    answers = iter(
        [
            "edit",
            json.dumps(
                [{"id": "1", "name": "write_file", "args": {"path": "a.txt", "content": "x"}}]
            ),
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    result = ask_user_for_approval({"tool_calls": [], "risk": "test"})

    assert result["decision"] == "approved"
    assert result["edited_tool_calls"][0]["name"] == "write_file"


def test_format_call_arguments_markdown_preserves_full_pretty_json() -> None:
    long_content = "x" * 600
    rendered = _format_call_arguments_markdown(
        {"name": "write_file", "args": {"path": "a.txt", "content": long_content}}
    )

    assert rendered.startswith("```json\n")
    assert rendered.endswith("\n```")
    assert '"path": "a.txt"' in rendered
    assert f'"content": "{long_content}"' in rendered
    assert "...[TRUNCATED]" not in rendered


def test_configure_line_editor_binds_common_delete_keys(monkeypatch) -> None:
    bindings: list[str] = []

    class FakeReadline:
        @staticmethod
        def parse_and_bind(binding: str) -> None:
            bindings.append(binding)

    monkeypatch.setattr(cli, "readline", FakeReadline)

    configure_line_editor()

    assert '"\\C-h": backward-delete-char' in bindings
    assert '"\\e[3~": delete-char' in bindings
