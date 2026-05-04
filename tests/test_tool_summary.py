from terminal_code_agent.schemas import ToolResult
from terminal_code_agent.tools import summarize_tool_result


def test_summarize_tool_result_includes_failure_details() -> None:
    raw = ToolResult(
        ok=False,
        tool="run_shell",
        error_type="retryable_error",
        message="命令退出码非 0: 1",
        hint="请根据 stdout/stderr 调整命令。",
        metadata={"stderr": "compile error"},
    ).model_dump_json()

    summary = summarize_tool_result(raw)

    assert summary["error_type"] == "retryable_error"
    assert summary["hint"] == "请根据 stdout/stderr 调整命令。"
    assert summary["stderr"] == "compile error"
