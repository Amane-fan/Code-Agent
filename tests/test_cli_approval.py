import json
from pathlib import Path
from types import SimpleNamespace

from rich.markdown import Markdown
from typer.testing import CliRunner

from terminal_code_agent import cli
from terminal_code_agent.cli import (
    _format_call_arguments_markdown,
    app,
    ask_user_for_approval,
    build_graph_config,
    configure_line_editor,
    parse_resume_command,
    print_final,
)

runner = CliRunner()


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


def test_print_final_renders_answer_as_markdown(monkeypatch) -> None:
    printed = []

    class FakeConsole:
        @staticmethod
        def print(renderable) -> None:
            printed.append(renderable)

    monkeypatch.setattr(cli, "console", FakeConsole)

    print_final({"final_answer": "**加粗**\n\n- 列表"})

    assert isinstance(printed[0].renderable, Markdown)


def test_parse_resume_command_returns_thread_id() -> None:
    assert parse_resume_command("/resume abc-123") == "abc-123"
    assert parse_resume_command("普通消息") is None


def test_parse_resume_command_rejects_invalid_shape() -> None:
    try:
        parse_resume_command("/resume")
    except ValueError as exc:
        assert "用法" in str(exc)
    else:  # pragma: no cover - defensive branch.
        raise AssertionError("expected ValueError")

    try:
        parse_resume_command("/resume a b")
    except ValueError as exc:
        assert "用法" in str(exc)
    else:  # pragma: no cover - defensive branch.
        raise AssertionError("expected ValueError")


def test_build_graph_config_uses_thread_id() -> None:
    assert build_graph_config("thread-a") == {"configurable": {"thread_id": "thread-a"}}


def test_cli_generates_new_thread_id_by_default(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--workdir",
            str(tmp_path),
            "--env-file",
            str(tmp_path / "missing.env"),
            "--no-color",
        ],
        input="exit\n",
        env={
            "CHECKPOINT_DB": str(tmp_path / "checkpoints.sqlite"),
            "LOG_DIR": str(tmp_path / "logs"),
        },
    )

    assert result.exit_code == 0
    assert "thread  default" not in result.output
    assert "thread  00000000-0000-0000-0000-000000000000" not in result.output
    assert (tmp_path / "checkpoints.sqlite").exists()


def test_cli_resume_switches_to_existing_thread(tmp_path: Path, monkeypatch) -> None:
    class FakeGraph:
        def get_state(self, config):
            if config["configurable"]["thread_id"] == "existing-thread":
                return SimpleNamespace(values={"messages": [{"role": "user", "content": "old"}]})
            return SimpleNamespace(values={})

    monkeypatch.setattr(cli, "build_graph", lambda *args, **kwargs: FakeGraph())

    result = runner.invoke(
        app,
        [
            "--workdir",
            str(tmp_path),
            "--env-file",
            str(tmp_path / "missing.env"),
            "--no-color",
        ],
        input="/resume existing-thread\nexit\n",
        env={
            "CHECKPOINT_DB": str(tmp_path / "checkpoints.sqlite"),
            "LOG_DIR": str(tmp_path / "logs"),
        },
    )

    assert result.exit_code == 0
    assert "已恢复 thread-id:" in result.output
    assert "existing-thread" in result.output


def test_cli_resume_keeps_current_thread_when_missing(tmp_path: Path, monkeypatch) -> None:
    class FakeGraph:
        def get_state(self, config):
            return SimpleNamespace(values={})

    monkeypatch.setattr(cli, "build_graph", lambda *args, **kwargs: FakeGraph())

    result = runner.invoke(
        app,
        [
            "--workdir",
            str(tmp_path),
            "--env-file",
            str(tmp_path / "missing.env"),
            "--no-color",
        ],
        input="/resume missing-thread\nexit\n",
        env={
            "CHECKPOINT_DB": str(tmp_path / "checkpoints.sqlite"),
            "LOG_DIR": str(tmp_path / "logs"),
        },
    )

    assert result.exit_code == 0
    assert "未找到 thread-id:" in result.output
    assert "missing-thread" in result.output
