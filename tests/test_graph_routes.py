from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from terminal_code_agent.config import Settings
from terminal_code_agent.graph import (
    _build_prompt_messages,
    build_graph,
    context_pack,
    route_budget_check,
    route_human_approval,
    route_model_result,
    route_tool_execute,
    route_tool_gate,
    skill_select,
    tool_gate,
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


class FakeRetryableToolErrorModel:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls.append([str(getattr(message, "content", "")) for message in messages])
        if len(self.calls) == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {"id": "call_1", "name": "read_file", "args": {"path": "missing.txt"}}
                ],
            )
        return AIMessage(content="已收到工具错误并重新规划。")


class FakeSkillSelectionModel:
    def __init__(self) -> None:
        self.prompt = ""

    def invoke(self, messages):
        self.prompt = "\n".join(str(getattr(message, "content", "")) for message in messages)
        return AIMessage(
            content='{"selected_skills":["python_project"],"reason":"匹配 Python 任务"}'
        )


class FakeRejectedApprovalModel:
    def __init__(self) -> None:
        self.calls = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        if len(self.calls) == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "write_file",
                        "args": {"path": "amane.py", "content": "print('Amane')"},
                    }
                ],
            )
        return AIMessage(content="已取消执行写文件。")


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


def test_retryable_tool_error_is_added_to_next_model_context(tmp_path: Path) -> None:
    settings = Settings(skills_dir=tmp_path / "skills")
    model = FakeRetryableToolErrorModel()
    graph = build_graph(InMemorySaver(), settings=settings, model=model)

    result = graph.invoke(
        {"thread_id": "test", "workdir": str(tmp_path), "user_input": "读取缺失文件"},
        config={"configurable": {"thread_id": "test"}},
    )

    assert result["final_answer"] == "已收到工具错误并重新规划。"
    assert len(model.calls) == 2
    assert result["tool_error"]["tool"] == "read_file"
    second_prompt = "\n".join(model.calls[1])
    assert "文件不存在: missing.txt" in second_prompt
    assert "工具观察" in second_prompt


def test_skill_select_uses_frontmatter_description(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "python_project"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        """---
name: python_project
description: Use when the user asks for Python project changes.
---

BODY SHOULD NOT BE USED FOR SKILL SELECTION.
""",
        encoding="utf-8",
    )
    settings = Settings(skills_dir=tmp_path / "skills")
    model = FakeSkillSelectionModel()

    result = skill_select({"user_input": "修改 Python 项目"}, settings=settings, model=model)

    assert result["selected_skills"] == ["python_project"]
    assert "Use when the user asks for Python project changes." in model.prompt
    assert "BODY SHOULD NOT BE USED FOR SKILL SELECTION." not in model.prompt
    assert "BODY SHOULD NOT BE USED FOR SKILL SELECTION." in result["skill_context"]


def test_skill_select_builds_model_when_not_injected(tmp_path: Path, monkeypatch) -> None:
    skill_dir = tmp_path / "skills" / "python_project"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        """---
name: python_project
description: Use when the user asks for Python project changes.
---
""",
        encoding="utf-8",
    )
    settings = Settings(skills_dir=tmp_path / "skills")
    model = FakeSkillSelectionModel()

    monkeypatch.setattr("terminal_code_agent.graph.build_chat_model", lambda settings: model)

    result = skill_select({"user_input": "修改 Python 项目"}, settings=settings)

    assert result["selected_skills"] == ["python_project"]
    assert "Use when the user asks for Python project changes." in model.prompt


def test_rejected_approval_adds_tool_message_for_pending_call(tmp_path: Path) -> None:
    settings = Settings(skills_dir=tmp_path / "skills")
    model = FakeRejectedApprovalModel()
    graph = build_graph(InMemorySaver(), settings=settings, model=model)
    config = {"configurable": {"thread_id": "test"}}

    interrupted = graph.invoke(
        {"thread_id": "test", "workdir": str(tmp_path), "user_input": "写文件"},
        config=config,
    )
    assert "__interrupt__" in interrupted

    result = graph.invoke(Command(resume={"decision": "rejected"}), config=config)

    assert result["final_answer"] == "已取消执行写文件。"
    assert len(model.calls) == 2
    tool_messages = [message for message in model.calls[1] if isinstance(message, ToolMessage)]
    assert any(
        message.tool_call_id == "call_1" and "用户拒绝" in str(message.content)
        for message in tool_messages
    )


def test_tool_gate_denied_adds_tool_message_for_pending_call(tmp_path: Path) -> None:
    result = tool_gate(
        {
            "workdir": str(tmp_path),
            "pending_tool_calls": [{"id": "call_1", "name": "unknown_tool", "args": {}}],
        },
        settings=Settings(skills_dir=tmp_path / "skills"),
    )

    assert result["tool_gate_route"] == "denied"
    assert result["messages"][0]["role"] == "tool"
    assert result["messages"][0]["tool_call_id"] == "call_1"
    assert "工具调用被拒绝" in result["messages"][0]["content"]


def test_model_prompt_skips_leading_tool_message_after_history_trim(tmp_path: Path) -> None:
    messages = [{"role": "user", "content": "dropped by history trim"}]
    messages.append(
        {
            "role": "tool",
            "content": "orphaned tool response",
            "tool_call_id": "call_1",
            "name": "run_shell",
        }
    )
    messages.extend(
        {"role": "assistant", "content": f"kept assistant message {index}"}
        for index in range(29)
    )

    prompt_messages = _build_prompt_messages(
        {
            "workdir": str(tmp_path),
            "messages": messages,
            "selected_skills": [],
            "skill_context": "",
            "context_summary": "",
            "observations": [],
            "tool_error": {},
        }
    )

    assert not isinstance(prompt_messages[1], ToolMessage)
    assert str(prompt_messages[1].content) == "kept assistant message 0"


def test_context_pack_skips_leading_tool_message_after_history_trim(tmp_path: Path) -> None:
    messages = [{"role": "user", "content": "dropped by history trim"}]
    messages.append(
        {
            "role": "tool",
            "content": "orphaned tool response",
            "tool_call_id": "call_1",
            "name": "run_shell",
        }
    )
    messages.extend(
        {"role": "assistant", "content": f"kept assistant message {index}"}
        for index in range(29)
    )

    result = context_pack(
        {
            "messages": messages,
            "context_summary": "",
            "selected_skills": [],
            "skill_context": "",
            "observations": [],
            "tool_error": {},
        },
        settings=Settings(skills_dir=tmp_path / "skills"),
    )

    assert result["context_messages"][0]["role"] == "assistant"
    assert result["context_messages"][0]["content"] == "kept assistant message 0"
