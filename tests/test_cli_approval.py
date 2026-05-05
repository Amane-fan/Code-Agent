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
    long_pattern = "x" * 600
    rendered = _format_call_arguments_markdown(
        {"name": "grep", "args": {"path": ".", "pattern": long_pattern}}
    )

    assert rendered.startswith("```json\n")
    assert rendered.endswith("\n```")
    assert '"path": "."' in rendered
    assert f'"pattern": "{long_pattern}"' in rendered
    assert "...[TRUNCATED]" not in rendered


def test_format_call_arguments_markdown_expands_write_file_content() -> None:
    content = "def greet():\n    print('hello')\n"

    rendered = _format_call_arguments_markdown(
        {"name": "write_file", "args": {"path": "hello.py", "content": content}}
    )

    assert '"path": "hello.py"' in rendered
    assert '"content": "<见下方代码块>"' in rendered
    assert '"content": "def greet():\\n    print(' not in rendered
    assert "```python\ndef greet():\n    print('hello')\n```" in rendered


def test_format_call_arguments_markdown_expands_apply_patch_patch() -> None:
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: app.py",
            "@@",
            "-print('old')",
            "+print('new')",
            "*** End Patch",
        ]
    )

    rendered = _format_call_arguments_markdown(
        {"name": "apply_patch", "args": {"patch": patch}}
    )

    assert '"patch": "<见下方代码块>"' in rendered
    assert '"patch": "*** Begin Patch\\n' not in rendered
    assert f"```diff\n{patch}\n```" in rendered


def test_format_call_arguments_markdown_keeps_run_shell_command_in_json() -> None:
    command = "python - <<'PY'\nprint('hello')\nPY"

    rendered = _format_call_arguments_markdown(
        {"name": "run_shell", "args": {"command": command, "timeout_seconds": 30}}
    )

    assert '"command": "python - <<' in rendered
    assert "\\nprint('hello')\\nPY" in rendered
    assert "```shell\n" not in rendered


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
