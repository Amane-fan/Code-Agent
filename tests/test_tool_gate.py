from pathlib import Path

from terminal_code_agent.config import Settings
from terminal_code_agent.tool_gate import evaluate_tool_calls


def test_readonly_tool_is_allowed(tmp_path: Path) -> None:
    result = evaluate_tool_calls(
        [{"id": "1", "name": "list_files", "args": {"path": "."}}],
        settings=Settings(skills_dir=tmp_path / "skills"),
        workdir=str(tmp_path),
    )

    assert result["tool_gate_route"] == "allowed"


def test_write_tool_needs_approval(tmp_path: Path) -> None:
    result = evaluate_tool_calls(
        [{"id": "1", "name": "write_file", "args": {"path": "a.txt", "content": "x"}}],
        settings=Settings(skills_dir=tmp_path / "skills"),
        workdir=str(tmp_path),
    )

    assert result["tool_gate_route"] == "needs_approval"
    assert result["approval_request"]["risk"]


def test_unknown_tool_is_denied(tmp_path: Path) -> None:
    result = evaluate_tool_calls(
        [{"id": "1", "name": "unknown_tool", "args": {}}],
        settings=Settings(skills_dir=tmp_path / "skills"),
        workdir=str(tmp_path),
    )

    assert result["tool_gate_route"] == "denied"
