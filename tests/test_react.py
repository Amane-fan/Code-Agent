from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Sequence

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langgraph.graph import StateGraph

from code_agent.agent import CodingAgent
from code_agent.config import AgentConfig
from code_agent.models import ModelCallUsage, ModelCompletion, ModelToolCall, TokenUsage
from code_agent.session import SessionStore
from code_agent.skill_selection import SKILL_SELECTOR_SYSTEM_INSTRUCTIONS


def _event_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return str(content)


def _batch_text(messages: Sequence[BaseMessage]) -> str:
    return "\n".join(_event_text(message) for message in messages)


def _summary(content: str) -> str:
    return json.dumps(
        {"role": "assistant", "type": "summary", "content": content},
        ensure_ascii=False,
    )


def _final(content: str, *, summary: str = "") -> str:
    payload = {"role": "assistant", "type": "final_answer", "content": content}
    if summary:
        payload["summary"] = summary
    return json.dumps(payload, ensure_ascii=False)


class SequencedProvider:
    name = "fake"

    def __init__(
        self,
        responses: list[str | ModelCompletion],
    ) -> None:
        self.responses = responses
        self.message_batches: list[list[BaseMessage]] = []
        self.bound_tool_names: list[list[str]] = []

    def complete(
        self,
        messages: Sequence[BaseMessage],
        *,
        model: str,
        tools: Sequence[BaseTool] | None = None,
    ) -> ModelCompletion:
        self.message_batches.append(list(messages))
        self.bound_tool_names.append([tool.name for tool in tools or []])
        if not self.responses:
            raise AssertionError("provider called too many times")
        response = self.responses.pop(0)
        if isinstance(response, ModelCompletion):
            return response
        return ModelCompletion(text=response)

    @property
    def prompts(self) -> list[str]:
        return [_batch_text(messages) for messages in self.message_batches]


class FailingOnceProvider(SequencedProvider):
    def __init__(self, response: str) -> None:
        super().__init__([response])
        self.fail_next = True

    def complete(
        self,
        messages: Sequence[BaseMessage],
        *,
        model: str,
        tools: Sequence[BaseTool] | None = None,
    ) -> ModelCompletion:
        self.message_batches.append(list(messages))
        self.bound_tool_names.append([tool.name for tool in tools or []])
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("selector unavailable")
        if not self.responses:
            raise AssertionError("provider called too many times")
        return ModelCompletion(text=self.responses.pop(0))


class ReactLoopTests(unittest.TestCase):
    def test_langgraph_dependency_is_available(self) -> None:
        self.assertIsNotNone(StateGraph)

    def test_react_runner_builds_langgraph_workflow(self) -> None:
        from code_agent.react import _build_react_graph

        graph = _build_react_graph()

        self.assertTrue(callable(getattr(graph, "invoke", None)))

    def test_tool_result_is_appended_to_next_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            provider = SequencedProvider(
                [
                    ModelCompletion(
                        text=_summary("需要读取 README。"),
                        tool_calls=[
                            ModelToolCall(
                                id="call_read",
                                name="read_file",
                                args={"path": "README.md"},
                            )
                        ],
                    ),
                    _final("README 是 Demo。"),
                ]
            )

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="offline"),
                provider_factory=lambda name: provider,
            ).run("总结 README", save_session=False)

            self.assertEqual(run.final_answer, "README 是 Demo。")
            self.assertEqual(run.response_text, "README 是 Demo。")
            self.assertEqual(run.iterations, 2)
            self.assertIn('"type": "tool_result"', provider.prompts[1])
            self.assertIn("# Demo", provider.prompts[1])
            self.assertEqual(
                [event.type for event in run.history],
                ["task", "summary", "tool_call", "tool_result", "final_answer"],
            )
            self.assertIn("read_file", provider.bound_tool_names[0])
            self.assertNotIn("<action>", provider.prompts[0])
            self.assertNotIn("<observation>", provider.prompts[1])

    def test_multiple_tool_calls_are_executed_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("alpha\n", encoding="utf-8")
            (root / "b.txt").write_text("beta\n", encoding="utf-8")
            provider = SequencedProvider(
                [
                    ModelCompletion(
                        text=_summary("读取两个文件。"),
                        tool_calls=[
                            ModelToolCall(id="call_a", name="read_file", args={"path": "a.txt"}),
                            ModelToolCall(id="call_b", name="read_file", args={"path": "b.txt"}),
                        ],
                    ),
                    _final("alpha beta"),
                ]
            )

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="offline"),
                provider_factory=lambda name: provider,
            ).run("read both", save_session=False)

            self.assertEqual(run.final_answer, "alpha beta")
            self.assertEqual(
                [event.call_id for event in run.history if event.type == "tool_result"],
                ["call_a", "call_b"],
            )
            self.assertLess(provider.prompts[1].index("alpha"), provider.prompts[1].index("beta"))

    def test_tool_call_replay_preserves_reasoning_content_for_thinking_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("alpha\n", encoding="utf-8")
            (root / "b.txt").write_text("beta\n", encoding="utf-8")
            provider = SequencedProvider(
                [
                    ModelCompletion(
                        text=_summary("读取两个文件。"),
                        tool_calls=[
                            ModelToolCall(id="call_a", name="read_file", args={"path": "a.txt"}),
                            ModelToolCall(id="call_b", name="read_file", args={"path": "b.txt"}),
                        ],
                        reasoning_content="thinking trace",
                    ),
                    _final("alpha beta"),
                ]
            )

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="offline"),
                provider_factory=lambda name: provider,
            ).run("read both", save_session=False)

            tool_call_messages = [
                message
                for message in provider.message_batches[1]
                if isinstance(message, AIMessage) and message.tool_calls
            ]
            self.assertEqual(run.final_answer, "alpha beta")
            self.assertEqual(len(tool_call_messages), 1)
            self.assertEqual(
                tool_call_messages[0].additional_kwargs["reasoning_content"],
                "thinking trace",
            )
            self.assertEqual(
                [call["id"] for call in tool_call_messages[0].tool_calls],
                ["call_a", "call_b"],
            )
            self.assertNotIn("thinking trace", provider.prompts[1])

    def test_model_call_usage_is_recorded_without_history_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = SequencedProvider(
                [
                    ModelCompletion(
                        text=_summary("需要列文件。"),
                        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                        tool_calls=[ModelToolCall(id="call_list", name="list_files", args={})],
                    ),
                    ModelCompletion(
                        text=_final("done"),
                        usage=TokenUsage(prompt_tokens=20, completion_tokens=6, total_tokens=26),
                    ),
                ]
            )

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="offline"),
                provider_factory=lambda name: provider,
            ).run("list files", save_session=False)

            self.assertEqual(run.final_answer, "done")
            self.assertEqual(len(run.model_calls), 2)
            self.assertEqual(run.model_calls[0].purpose, "task")
            first_usage = run.model_calls[0].usage
            second_usage = run.model_calls[1].usage
            assert first_usage is not None
            assert second_usage is not None
            self.assertEqual(first_usage.total_tokens, 15)
            self.assertEqual(second_usage.prompt_tokens, 20)

    def test_skill_selection_model_call_runs_inside_graph_before_main_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            (root / "workspace-only.txt").write_text(
                "workspace content must stay out",
                encoding="utf-8",
            )
            skills_root = Path(tmp) / "skills"
            skill_dir = skills_root / "python"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: python\n"
                "description: Use when editing Python code.\n"
                "---\n\n"
                "Full Python skill body.\n",
                encoding="utf-8",
            )
            provider = SequencedProvider(
                [
                    ModelCompletion(
                        text='{"skills":["python"]}',
                        usage=TokenUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
                    ),
                    _final("skill selected"),
                ]
            )

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="openai", skills_path=skills_root),
                provider_factory=lambda name: provider,
            ).run("使用 python skill", save_session=False)

            self.assertEqual(run.final_answer, "skill selected")
            self.assertEqual([call.purpose for call in run.model_calls], ["skill_selection", "task"])
            self.assertTrue(run.model_calls[0].ok)
            self.assertEqual(
                run.model_calls[0].system_instructions,
                SKILL_SELECTOR_SYSTEM_INSTRUCTIONS,
            )
            self.assertIn("Full Python skill body.", run.model_calls[1].system_instructions)
            selection_usage = run.model_calls[0].usage
            assert selection_usage is not None
            self.assertEqual(selection_usage.total_tokens, 5)
            self.assertIn("Available skills JSON", provider.prompts[0])
            self.assertIn('"name": "python"', provider.prompts[0])
            self.assertIn("使用 python skill", provider.prompts[0])
            self.assertNotIn("workspace content must stay out", provider.prompts[0])
            self.assertIn("load_skill_resources", provider.bound_tool_names[1])

    def test_skill_selection_failure_continues_without_loaded_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            skills_root = Path(tmp) / "skills"
            skill_dir = skills_root / "python"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: python\n"
                "description: Use when editing Python code.\n"
                "---\n\n"
                "Full Python skill body.\n",
                encoding="utf-8",
            )
            provider = SequencedProvider(["not json", _final("continued")])

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="openai", skills_path=skills_root),
                provider_factory=lambda name: provider,
            ).run("task", save_session=False)

            self.assertEqual(run.final_answer, "continued")
            self.assertEqual([call.purpose for call in run.model_calls], ["skill_selection", "task"])
            self.assertFalse(run.model_calls[0].ok)
            self.assertIn("invalid skill selection JSON", run.model_calls[0].error)
            self.assertNotIn("Full Python skill body.", run.model_calls[1].system_instructions)

    def test_skill_selection_provider_error_continues_without_loaded_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            skills_root = Path(tmp) / "skills"
            skill_dir = skills_root / "python"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: python\n"
                "description: Use when editing Python code.\n"
                "---\n\n"
                "Full Python skill body.\n",
                encoding="utf-8",
            )
            provider = FailingOnceProvider(_final("continued"))

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="openai", skills_path=skills_root),
                provider_factory=lambda name: provider,
            ).run("task", save_session=False)

            self.assertEqual(run.final_answer, "continued")
            self.assertFalse(run.model_calls[0].ok)
            self.assertIn("selector unavailable", run.model_calls[0].error)

    def test_skill_selection_ignores_unknown_skill_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            skills_root = Path(tmp) / "skills"
            skill_dir = skills_root / "python"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: python\n"
                "description: Use when editing Python code.\n"
                "---\n\n"
                "Full Python skill body.\n",
                encoding="utf-8",
            )
            provider = SequencedProvider(['{"skills":["missing","python"]}', _final("continued")])

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="openai", skills_path=skills_root),
                provider_factory=lambda name: provider,
            ).run("task", save_session=False)

            self.assertEqual(run.final_answer, "continued")
            self.assertTrue(run.model_calls[0].ok)
            self.assertIn("ignored unknown skills: missing", run.model_calls[0].error)

    def test_same_agent_remembers_previous_turns_but_new_agent_starts_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window_provider = SequencedProvider([_final("first answer"), _final("second answer")])
            clean_provider = SequencedProvider([_final("clean answer")])
            config = AgentConfig(workspace_path=root, provider="offline")

            agent = CodingAgent(config, provider_factory=lambda name: window_provider)
            agent.run("first task", save_session=False)
            agent.run("second task", save_session=False)
            CodingAgent(config, provider_factory=lambda name: clean_provider).run(
                "clean task",
                save_session=False,
            )

            self.assertIn('"content": "first task"', window_provider.prompts[0])
            self.assertIn('"content": "second task"', window_provider.prompts[1])
            self.assertIn('"content": "first answer"', window_provider.prompts[1])
            self.assertNotIn("<final_answer>", window_provider.prompts[1])
            self.assertIn('"content": "clean task"', clean_provider.prompts[0])
            self.assertNotIn("first task", clean_provider.prompts[0])

    def test_manual_compact_uses_model_summary_and_keeps_recent_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = SequencedProvider(
                [
                    _final("first answer"),
                    _final("second answer"),
                    _final("third answer"),
                    _final("remember first task"),
                    _final("fourth answer"),
                ]
            )
            agent = CodingAgent(
                AgentConfig(workspace_path=root, provider="offline"),
                provider_factory=lambda name: provider,
            )

            agent.run("first task", save_session=False)
            agent.run("second task", save_session=False)
            agent.run("third task", save_session=False)
            result = agent.compact_memory()
            agent.run("fourth task", save_session=False)

            self.assertTrue(result.compacted)
            self.assertFalse(result.used_fallback)
            self.assertEqual(result.summary, "remember first task")
            self.assertIn('"type": "memory"', provider.prompts[-1])
            self.assertIn("remember first task", provider.prompts[-1])
            self.assertNotIn('"content": "first task"', provider.prompts[-1])
            self.assertIn('"content": "second task"', provider.prompts[-1])
            self.assertIn('"content": "third task"', provider.prompts[-1])

    def test_manual_compact_saves_model_call_usage_to_session_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            session_root = Path(tmp) / "sessions"
            provider = SequencedProvider(
                [
                    _final("first answer"),
                    _final("second answer"),
                    _final("third answer"),
                    ModelCompletion(
                        text=_final("memory"),
                        usage=TokenUsage(prompt_tokens=30, completion_tokens=10, total_tokens=40),
                    ),
                ]
            )
            agent = CodingAgent(
                AgentConfig(
                    workspace_path=root,
                    provider="offline",
                    session_root=session_root,
                ),
                provider_factory=lambda name: provider,
            )

            agent.run("first task", save_session=True)
            agent.run("second task", save_session=True)
            agent.run("third task", save_session=True)
            result = agent.compact_memory(save_session=True)

            self.assertEqual(result.model_calls[0].purpose, "compaction")
            compact_usage = result.model_calls[0].usage
            assert compact_usage is not None
            self.assertEqual(compact_usage.total_tokens, 40)
            session_files = list((session_root / "sessions").glob("*.json"))
            self.assertEqual(len(session_files), 1)
            data = json.loads(session_files[0].read_text(encoding="utf-8"))
            self.assertEqual(data["model_calls"][-1]["purpose"], "compaction")
            self.assertEqual(data["model_calls"][-1]["system_instructions"], "")
            self.assertEqual(data["model_calls"][-1]["usage"]["total_tokens"], 40)

    def test_auto_compact_model_call_usage_is_attached_to_current_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            session_root = Path(tmp) / "sessions"
            provider = SequencedProvider(
                [
                    _final("first answer"),
                    _final("second answer"),
                    ModelCompletion(
                        text=_final("auto memory"),
                        usage=TokenUsage(prompt_tokens=21, completion_tokens=9, total_tokens=30),
                    ),
                ]
            )
            agent = CodingAgent(
                AgentConfig(
                    workspace_path=root,
                    provider="offline",
                    session_root=session_root,
                    max_conversation_chars=1,
                    recent_turns_to_keep=1,
                ),
                provider_factory=lambda name: provider,
            )

            agent.run("first task", save_session=True)
            second = agent.run("second task", save_session=True)

            self.assertEqual(second.model_calls[-1].purpose, "compaction")
            compact_usage = second.model_calls[-1].usage
            assert compact_usage is not None
            self.assertEqual(compact_usage.total_tokens, 30)
            data = json.loads(next((session_root / "sessions").glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(data["runs"][1]["model_calls"][-1]["purpose"], "compaction")

    def test_shell_tool_call_requires_user_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = SequencedProvider(
                [
                    ModelCompletion(
                        text=_summary("运行命令。"),
                        tool_calls=[
                            ModelToolCall(
                                id="call_shell",
                                name="run_shell",
                                args={"command": "printf hello"},
                            )
                        ],
                    ),
                    _final("ok"),
                ]
            )
            approvals: list[str] = []

            def approve(command: str) -> bool:
                approvals.append(command)
                return True

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="offline"),
                provider_factory=lambda name: provider,
            ).run("run command", shell_approval=approve, save_session=False)

            self.assertEqual(approvals, ["printf hello"])
            self.assertEqual(run.final_answer, "ok")
            self.assertIn("hello", provider.prompts[1])

    def test_loop_stops_at_max_iterations_after_last_tool_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = SequencedProvider(
                [
                    ModelCompletion(
                        text=_summary("继续。"),
                        tool_calls=[ModelToolCall(id="call_list", name="list_files", args={})],
                    )
                ]
            )

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="offline", max_iterations=1),
                provider_factory=lambda name: provider,
            ).run("loop once", save_session=False)

            self.assertEqual(run.iterations, 1)
            self.assertEqual(
                [event.type for event in run.history],
                ["task", "summary", "tool_call", "tool_result", "final_answer"],
            )
            self.assertIn("maximum iteration limit", run.final_answer)

    def test_session_log_contains_json_events_without_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            session_root = Path(tmp) / "sessions"
            provider = SequencedProvider([_final("answer", summary="完成。")])

            run = CodingAgent(
                AgentConfig(
                    workspace_path=root,
                    provider="offline",
                    session_root=session_root,
                ),
                provider_factory=lambda name: provider,
            ).run("task", save_session=True)

            self.assertIsNotNone(run.session_path)
            assert run.session_path is not None
            data = json.loads(run.session_path.read_text(encoding="utf-8"))
            self.assertEqual(data["final_answer"], "answer")
            self.assertEqual(data["history"][0]["type"], "task")
            self.assertEqual(data["history"][1]["type"], "summary")
            self.assertEqual(data["history"][-1]["type"], "final_answer")
            self.assertNotIn("tag", data["history"][0])

    def test_session_log_records_system_instructions_only_once_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            session_root = Path(tmp) / "sessions"
            provider = SequencedProvider([_final("first answer"), _final("second answer")])
            agent = CodingAgent(
                AgentConfig(
                    workspace_path=root,
                    provider="offline",
                    session_root=session_root,
                ),
                provider_factory=lambda name: provider,
            )

            agent.run("first task", save_session=True)
            agent.run("second task", save_session=True)

            session_files = list((session_root / "sessions").glob("*.json"))
            self.assertEqual(len(session_files), 1)
            data = json.loads(session_files[0].read_text(encoding="utf-8"))
            self.assertIn("Available bound tools", data["model_calls"][0]["system_instructions"])
            self.assertEqual(data["model_calls"][1]["system_instructions"], "")
            self.assertEqual(len(data["runs"]), 2)

    def test_empty_session_log_can_record_compaction_system_instructions_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session_store = SessionStore(Path(tmp) / "sessions")

            session_path = session_store.append_model_calls(
                [
                    ModelCallUsage(
                        provider="fake",
                        model="test-model",
                        purpose="compaction",
                        ok=True,
                        system_instructions="memory compaction system prompt",
                    )
                ]
            )

            data = json.loads(session_path.read_text(encoding="utf-8"))
            self.assertEqual(
                data["model_calls"][0]["system_instructions"],
                "memory compaction system prompt",
            )


if __name__ == "__main__":
    unittest.main()
