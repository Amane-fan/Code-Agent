from pathlib import Path

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from terminal_code_agent.config import Settings
from terminal_code_agent.graph import (
    build_graph,
    route_budget_check,
    route_human_approval,
    route_model_result,
    route_tool_execute,
    route_tool_gate,
    tool_repair,
)


class FakeToolModel:
    def __init__(self) -> None:
        self.calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[{"id": "call_1", "name": "list_files", "args": {"path": "."}}],
            )
        return AIMessage(content="已查看项目结构。")


class FakePlainTextModel:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls.append([str(getattr(message, "content", "")) for message in messages])
        return AIMessage(content="不是 JSON")


def test_route_functions_read_state_fields() -> None:
    assert route_budget_check({"budget_status": "over_limit"}) == "over_limit"
    assert route_model_result({"model_route": "tool_calls"}) == "tool_calls"
    assert route_tool_gate({"tool_gate_route": "needs_approval"}) == "needs_approval"
    assert route_human_approval({"approval_result": "approved"}) == "approved"
    assert route_tool_execute({"tool_execute_status": "retryable_error"}) == "retryable_error"


def test_build_graph_compiles(tmp_path) -> None:
    graph = build_graph(InMemorySaver(), settings=Settings(skills_dir=tmp_path / "skills"))

    assert graph is not None


def test_graph_readonly_tool_flow_with_fake_model(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    settings = Settings(skills_dir=tmp_path / "skills")
    graph = build_graph(InMemorySaver(), settings=settings, model=FakeToolModel())

    result = graph.invoke(
        {"thread_id": "test", "workdir": str(tmp_path), "user_input": "查看结构"},
        config={"configurable": {"thread_id": "test"}},
    )

    assert result["final_answer"] == "已查看项目结构。"
    assert result["tool_results"][0]["tool"] == "list_files"


def test_plain_text_final_answer_does_not_need_json_repair(tmp_path: Path) -> None:
    settings = Settings(skills_dir=tmp_path / "skills")
    model = FakePlainTextModel()
    graph = build_graph(InMemorySaver(), settings=settings, model=model)

    result = graph.invoke(
        {"thread_id": "test", "workdir": str(tmp_path), "user_input": "直接回答"},
        config={"configurable": {"thread_id": "test"}},
    )

    assert result["final_answer"] == "不是 JSON"
    assert len(model.calls) == 1


def test_tool_repair_fallback_includes_tool_error() -> None:
    result = tool_repair(
        {
            "tool_repair_attempts": 3,
            "tool_error": {
                "tool": "apply_patch",
                "message": "patch 校验失败",
                "hint": "请重新读取相关文件后生成可应用的 patch。",
            },
        },
        settings=Settings(max_tool_repair_attempts=3),
    )

    assert result["force_final"] is True
    assert "apply_patch 调用失败" in result["final_answer"]
    assert "patch 校验失败" in result["final_answer"]
