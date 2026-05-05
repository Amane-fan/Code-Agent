from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from terminal_code_agent.config import Settings
from terminal_code_agent.graph import (
    _build_prompt_messages,
    _format_model_info,
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


class FakePersistentModel:
    def __init__(self, label: str) -> None:
        self.label = label
        self.calls: list[list[str]] = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls.append([str(getattr(message, "content", "")) for message in messages])
        return AIMessage(content=f"{self.label} answer")


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


def test_sqlite_checkpointer_restores_history_across_graph_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "checkpoints.sqlite"
    settings = Settings(skills_dir=tmp_path / "skills")

    with SqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        first_model = FakePersistentModel("first")
        graph = build_graph(checkpointer, settings=settings, model=first_model)
        result = graph.invoke(
            {"thread_id": "persisted", "workdir": str(tmp_path), "user_input": "第一轮"},
            config={"configurable": {"thread_id": "persisted"}},
        )

    assert result["final_answer"] == "first answer"

    with SqliteSaver.from_conn_string(str(db_path)) as checkpointer:
        second_model = FakePersistentModel("second")
        graph = build_graph(checkpointer, settings=settings, model=second_model)
        result = graph.invoke(
            {"thread_id": "persisted", "workdir": str(tmp_path), "user_input": "第二轮"},
            config={"configurable": {"thread_id": "persisted"}},
        )

    assert result["final_answer"] == "second answer"
    second_prompt = "\n".join(second_model.calls[0])
    assert "第一轮" in second_prompt
    assert "first answer" in second_prompt
    assert "第二轮" in second_prompt


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
        },
        Settings(skills_dir=tmp_path / "skills"),
    )

    assert not isinstance(prompt_messages[1], ToolMessage)
    assert str(prompt_messages[1].content) == "kept assistant message 0"


def test_model_prompt_preserves_reasoning_content_within_active_tool_turn(
    tmp_path: Path,
) -> None:
    prompt_messages = _build_prompt_messages(
        {
            "workdir": str(tmp_path),
            "messages": [
                {"role": "user", "content": "写文件"},
                {
                    "role": "assistant",
                    "content": "",
                    "metadata": {
                        "reasoning_content": "需要调用写文件工具。",
                        "tool_calls": [
                            {"id": "call_1", "name": "write_file", "args": {"path": "a.txt"}}
                        ],
                    },
                },
                {
                    "role": "tool",
                    "content": '{"ok": true}',
                    "tool_call_id": "call_1",
                    "name": "write_file",
                },
            ],
            "selected_skills": [],
            "skill_context": "",
            "context_summary": "",
            "observations": [],
            "tool_error": {},
        },
        Settings(skills_dir=tmp_path / "skills"),
    )

    assistant_message = next(
        message for message in prompt_messages if isinstance(message, AIMessage)
    )
    assert assistant_message.additional_kwargs["reasoning_content"] == "需要调用写文件工具。"


def test_model_prompt_clears_stale_reasoning_content_after_new_user_turn(
    tmp_path: Path,
) -> None:
    prompt_messages = _build_prompt_messages(
        {
            "workdir": str(tmp_path),
            "messages": [
                {"role": "user", "content": "第一轮"},
                {
                    "role": "assistant",
                    "content": "",
                    "metadata": {
                        "reasoning_content": "第一轮内部思考。",
                        "tool_calls": [{"id": "call_1", "name": "list_files", "args": {}}],
                    },
                },
                {
                    "role": "tool",
                    "content": '{"ok": true}',
                    "tool_call_id": "call_1",
                    "name": "list_files",
                },
                {"role": "user", "content": "第二轮"},
            ],
            "selected_skills": [],
            "skill_context": "",
            "context_summary": "",
            "observations": [],
            "tool_error": {},
        },
        Settings(skills_dir=tmp_path / "skills"),
    )

    assistant_message = next(
        message for message in prompt_messages if isinstance(message, AIMessage)
    )
    assert "reasoning_content" not in assistant_message.additional_kwargs


def test_model_prompt_includes_model_info(tmp_path: Path) -> None:
    settings = Settings(
        skills_dir=tmp_path / "skills",
        model_name="gpt-test",
        model_temperature=0.2,
        model_max_tokens=1234,
        model_context_window=9999,
        model_timeout_seconds=45,
    )

    prompt_messages = _build_prompt_messages(
        {
            "workdir": str(tmp_path),
            "messages": [],
            "selected_skills": [],
            "skill_context": "",
            "context_summary": "",
            "observations": [],
            "tool_error": {},
        },
        settings,
    )

    system_prompt = str(prompt_messages[0].content)
    assert "当前模型信息：" in system_prompt
    assert _format_model_info(settings) in system_prompt


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


def test_context_pack_clears_stale_reasoning_content_after_new_user_turn(
    tmp_path: Path,
) -> None:
    result = context_pack(
        {
            "messages": [
                {"role": "user", "content": "第一轮"},
                {
                    "role": "assistant",
                    "content": "",
                    "metadata": {
                        "reasoning_content": "第一轮内部思考。",
                        "tool_calls": [{"id": "call_1", "name": "list_files", "args": {}}],
                    },
                },
                {"role": "user", "content": "第二轮"},
            ],
            "context_summary": "",
            "selected_skills": [],
            "skill_context": "",
            "observations": [],
            "tool_error": {},
        },
        settings=Settings(skills_dir=tmp_path / "skills"),
    )

    assert "reasoning_content" not in result["context_messages"][1].get("metadata", {})
