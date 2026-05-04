import json

from terminal_code_agent.cli import ask_user_for_approval


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
