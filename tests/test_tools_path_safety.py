from pathlib import Path

from terminal_code_agent.config import Settings
from terminal_code_agent.tool_runtime import parse_tool_result, resolve_in_root
from terminal_code_agent.tools import invoke_tool


def _settings(tmp_path: Path) -> Settings:
    return Settings(skills_dir=tmp_path / "skills")


def test_resolve_in_root_rejects_escape(tmp_path: Path) -> None:
    try:
        resolve_in_root(tmp_path, "../secret")
    except Exception as exc:
        assert "路径逃逸" in str(exc)
    else:
        raise AssertionError("expected path escape rejection")


def test_read_file_rejects_sensitive_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=secret", encoding="utf-8")

    raw = invoke_tool("read_file", {"path": ".env"}, workdir=tmp_path, settings=_settings(tmp_path))
    result = parse_tool_result(raw)

    assert result.ok is False
    assert result.error_type == "fatal_error"


def test_read_file_line_range_and_grep(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("a = 1\nneedle = 2\nc = 3\n", encoding="utf-8")
    settings = _settings(tmp_path)

    read_raw = invoke_tool(
        "read_file",
        {"path": "src/app.py", "start_line": 2, "end_line": 2},
        workdir=tmp_path,
        settings=settings,
    )
    grep_raw = invoke_tool(
        "grep",
        {"pattern": "needle", "path": ".", "glob": "*.py"},
        workdir=tmp_path,
        settings=settings,
    )

    assert "2: needle = 2" in parse_tool_result(read_raw).data["content"]
    assert parse_tool_result(grep_raw).data["matches"][0]["line"] == 2


def test_list_and_search_files(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("print(1)", encoding="utf-8")
    settings = _settings(tmp_path)

    listed = parse_tool_result(invoke_tool("list_files", {}, workdir=tmp_path, settings=settings))
    searched = parse_tool_result(
        invoke_tool("search_files", {"pattern": "*.py"}, workdir=tmp_path, settings=settings)
    )

    assert listed.ok is True
    assert searched.data["matches"] == ["a.py"]


def test_write_file_create_only_existing_fails(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("old", encoding="utf-8")

    result = parse_tool_result(
        invoke_tool(
            "write_file",
            {"path": "a.txt", "content": "new"},
            workdir=tmp_path,
            settings=_settings(tmp_path),
        )
    )

    assert result.ok is False
    assert result.error_type == "retryable_error"


def test_apply_patch_rejects_illegal_path(tmp_path: Path) -> None:
    patch = "--- a/../x\n+++ b/../x\n@@ -0,0 +1 @@\n+bad\n"

    result = parse_tool_result(
        invoke_tool("apply_patch", {"patch": patch}, workdir=tmp_path, settings=_settings(tmp_path))
    )

    assert result.ok is False
    assert result.error_type == "fatal_error"


def test_run_shell_rejects_dangerous_command(tmp_path: Path) -> None:
    result = parse_tool_result(
        invoke_tool(
            "run_shell", {"command": "cat .env"}, workdir=tmp_path, settings=_settings(tmp_path)
        )
    )

    assert result.ok is False
    assert result.error_type == "fatal_error"


def test_load_skill_resource_rejects_escape(tmp_path: Path) -> None:
    skills = tmp_path / "skills" / "python_project"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("ok", encoding="utf-8")

    result = parse_tool_result(
        invoke_tool(
            "load_skill_resource",
            {"skill_name": "python_project", "resource_path": "../secret.txt"},
            workdir=tmp_path,
            settings=_settings(tmp_path),
        )
    )

    assert result.ok is False
    assert result.error_type == "fatal_error"
