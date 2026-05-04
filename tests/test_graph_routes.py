import json
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
        return AIMessage(
            content=json.dumps(
                {
                    "type": "final",
                    "answer": "已查看项目结构。",
                    "summary": "调用 list_files。",
                    "changed_files": [],
                    "commands_run": [],
                    "risks_or_notes": [],
                    "next_steps": [],
                },
                ensure_ascii=False,
            )
        )


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

    assert result["final_json"]["type"] == "final"
    assert result["tool_results"][0]["tool"] == "list_files"
