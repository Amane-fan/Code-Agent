from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from langgraph.graph import StateGraph

from code_agent.agent import CodingAgent
from code_agent.config import AgentConfig
from code_agent.models import ModelCompletion, TokenUsage, WorkspaceContext


class SequencedProvider:
    name = "fake"

    def __init__(self, responses: list[str | ModelCompletion]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def complete(self, prompt: str, context: WorkspaceContext, *, model: str) -> str | ModelCompletion:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("provider called too many times")
        return self.responses.pop(0)


class ReactLoopTests(unittest.TestCase):
    def test_langgraph_dependency_is_available(self) -> None:
        self.assertIsNotNone(StateGraph)

    def test_react_runner_builds_langgraph_workflow(self) -> None:
        from code_agent.react import _build_react_graph

        graph = _build_react_graph()

        self.assertTrue(callable(getattr(graph, "invoke", None)))

    def test_tool_observation_is_appended_to_next_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            provider = SequencedProvider(
                [
                    '<summary>需要读取 README。</summary>\n'
                    '<action>{"tool":"read_file","args":{"path":"README.md"}}</action>',
                    "<summary>已经拿到文件内容。</summary>\n<final_answer>README 是 Demo。</final_answer>",
                ]
            )

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="offline"),
                provider_factory=lambda name: provider,
            ).run("总结 README", save_session=False)

            self.assertEqual(run.final_answer, "README 是 Demo。")
            self.assertEqual(run.response_text, "README 是 Demo。")
            self.assertEqual(run.iterations, 2)
            self.assertIn("<observation>", provider.prompts[1])
            self.assertIn("# Demo", provider.prompts[1])
            self.assertEqual([event.kind for event in run.history], ["task", "summary", "action", "observation", "summary", "final_answer"])
            self.assertNotIn("Only use these tools", provider.prompts[0])
            self.assertNotIn("Tool schemas", provider.prompts[0])
            self.assertNotIn("Workspace:", provider.prompts[0])

    def test_model_call_usage_is_recorded_without_history_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = SequencedProvider(
                [
                    ModelCompletion(
                        text='<summary>需要列文件。</summary>\n'
                        '<action>{"tool":"list_files","args":{}}</action>',
                        usage=TokenUsage(
                            prompt_tokens=10,
                            completion_tokens=5,
                            total_tokens=15,
                        ),
                    ),
                    ModelCompletion(
                        text="<summary>完成。</summary>\n<final_answer>done</final_answer>",
                        usage=TokenUsage(
                            prompt_tokens=20,
                            completion_tokens=6,
                            total_tokens=26,
                        ),
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
            self.assertEqual(
                [event.kind for event in run.history],
                ["task", "summary", "action", "observation", "summary", "final_answer"],
            )

    def test_string_provider_response_records_unknown_model_call_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = SequencedProvider(
                ["<summary>完成。</summary>\n<final_answer>done</final_answer>"]
            )

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="offline"),
                provider_factory=lambda name: provider,
            ).run("task", save_session=False)

            self.assertEqual(len(run.model_calls), 1)
            self.assertEqual(run.model_calls[0].purpose, "task")
            self.assertIsNone(run.model_calls[0].usage)

    def test_unclosed_final_answer_tag_does_not_render_protocol_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = SequencedProvider(
                [
                    "<summary>直接回答用户问题。</summary>\n\n"
                    "<final_answer>\n我是 Code Agent。"
                ]
            )

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="offline"),
                provider_factory=lambda name: provider,
            ).run("你是什么模型", save_session=False)

            self.assertEqual(run.final_answer, "我是 Code Agent。")
            self.assertEqual(run.history[-1].kind, "final_answer")
            self.assertEqual(run.history[-1].content, "我是 Code Agent。")

    def test_load_skill_observation_is_appended_to_next_model_call(self) -> None:
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
            provider = SequencedProvider(
                [
                    '<summary>需要加载技能。</summary>\n'
                    '<action>{"tool":"load_skill","args":{"name":"python"}}</action>',
                    "<summary>已经拿到技能。</summary>\n<final_answer>skill loaded</final_answer>",
                ]
            )

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="offline", skills_path=skills_root),
                provider_factory=lambda name: provider,
            ).run("使用 python skill", save_session=False)

            self.assertEqual(run.final_answer, "skill loaded")
            self.assertIn("Full Python skill body.", provider.prompts[1])
            self.assertIn('"name": "load_skill"', provider.prompts[1])

    def test_same_agent_remembers_previous_turns_but_new_agent_starts_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            window_provider = SequencedProvider(
                [
                    "<summary>完成。</summary>\n<final_answer>first answer</final_answer>",
                    "<summary>完成。</summary>\n<final_answer>second answer</final_answer>",
                ]
            )
            clean_provider = SequencedProvider(
                ["<summary>完成。</summary>\n<final_answer>clean answer</final_answer>"]
            )
            config = AgentConfig(workspace_path=root, provider="offline")

            agent = CodingAgent(config, provider_factory=lambda name: window_provider)
            agent.run(
                "first task",
                save_session=False,
            )
            agent.run(
                "second task",
                save_session=False,
            )
            CodingAgent(config, provider_factory=lambda name: clean_provider).run(
                "clean task",
                save_session=False,
            )

            self.assertIn("<task>first task</task>", window_provider.prompts[0])
            self.assertIn("<task>second task</task>", window_provider.prompts[1])
            self.assertIn("<final_answer>first answer</final_answer>", window_provider.prompts[1])
            self.assertIn("<task>clean task</task>", clean_provider.prompts[0])
            self.assertNotIn("first task", clean_provider.prompts[0])

    def test_manual_compact_uses_model_summary_and_keeps_recent_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = SequencedProvider(
                [
                    "<summary>完成。</summary>\n<final_answer>first answer</final_answer>",
                    "<summary>完成。</summary>\n<final_answer>second answer</final_answer>",
                    "<summary>完成。</summary>\n<final_answer>third answer</final_answer>",
                    "<summary>压缩完成。</summary>\n<final_answer>remember first task</final_answer>",
                    "<summary>完成。</summary>\n<final_answer>fourth answer</final_answer>",
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
            self.assertIn("<memory>remember first task</memory>", provider.prompts[-1])
            self.assertNotIn("<task>first task</task>", provider.prompts[-1])
            self.assertIn("<task>second task</task>", provider.prompts[-1])
            self.assertIn("<task>third task</task>", provider.prompts[-1])
            self.assertIn("<task>fourth task</task>", provider.prompts[-1])

    def test_manual_compact_saves_model_call_usage_to_session_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            session_root = Path(tmp) / "sessions"
            provider = SequencedProvider(
                [
                    "<summary>完成。</summary>\n<final_answer>first answer</final_answer>",
                    "<summary>完成。</summary>\n<final_answer>second answer</final_answer>",
                    "<summary>完成。</summary>\n<final_answer>third answer</final_answer>",
                    ModelCompletion(
                        text="<summary>压缩完成。</summary>\n<final_answer>memory</final_answer>",
                        usage=TokenUsage(
                            prompt_tokens=30,
                            completion_tokens=10,
                            total_tokens=40,
                        ),
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
            self.assertEqual(data["model_calls"][-1]["usage"]["total_tokens"], 40)
            self.assertEqual(len(data["runs"]), 3)

    def test_compact_falls_back_when_model_summary_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = SequencedProvider(
                [
                    "<summary>完成。</summary>\n<final_answer>first answer</final_answer>",
                    "<summary>完成。</summary>\n<final_answer>second answer</final_answer>",
                    "<summary>完成。</summary>\n<final_answer>third answer</final_answer>",
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

            self.assertTrue(result.compacted)
            self.assertTrue(result.used_fallback)
            self.assertIn("first task", result.summary)
            self.assertIn("first answer", result.summary)

    def test_auto_compact_when_conversation_exceeds_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = SequencedProvider(
                [
                    "<summary>完成。</summary>\n<final_answer>first answer</final_answer>",
                    "<summary>完成。</summary>\n<final_answer>second answer</final_answer>",
                    "<summary>压缩完成。</summary>\n<final_answer>auto memory</final_answer>",
                    "<summary>完成。</summary>\n<final_answer>third answer</final_answer>",
                ]
            )
            agent = CodingAgent(
                AgentConfig(
                    workspace_path=root,
                    provider="offline",
                    max_conversation_chars=1,
                    recent_turns_to_keep=1,
                ),
                provider_factory=lambda name: provider,
            )

            agent.run("first task", save_session=False)
            agent.run("second task", save_session=False)
            agent.run("third task", save_session=False)

            self.assertIn("auto memory", agent.memory_status())
            self.assertIn("<memory>auto memory</memory>", provider.prompts[-1])

    def test_auto_compact_model_call_usage_is_attached_to_current_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            session_root = Path(tmp) / "sessions"
            provider = SequencedProvider(
                [
                    "<summary>完成。</summary>\n<final_answer>first answer</final_answer>",
                    "<summary>完成。</summary>\n<final_answer>second answer</final_answer>",
                    ModelCompletion(
                        text="<summary>压缩完成。</summary>\n<final_answer>auto memory</final_answer>",
                        usage=TokenUsage(
                            prompt_tokens=21,
                            completion_tokens=9,
                            total_tokens=30,
                        ),
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
            session_files = list((session_root / "sessions").glob("*.json"))
            self.assertEqual(len(session_files), 1)
            data = json.loads(session_files[0].read_text(encoding="utf-8"))
            self.assertEqual(data["runs"][1]["model_calls"][-1]["purpose"], "compaction")
            self.assertEqual(data["model_calls"][-1]["usage"]["total_tokens"], 30)

    def test_invalid_action_json_returns_observation_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = SequencedProvider(
                [
                    "<summary>格式错误。</summary>\n<action>{bad json}</action>",
                    "<summary>修正。</summary>\n<final_answer>done</final_answer>",
                ]
            )

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="offline"),
                provider_factory=lambda name: provider,
            ).run("do it", save_session=False)

            self.assertEqual(run.final_answer, "done")
            self.assertIn("invalid action JSON", provider.prompts[1])

    def test_shell_action_requires_user_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = SequencedProvider(
                [
                    '<summary>运行命令。</summary>\n'
                    '<action>{"tool":"run_shell","args":{"command":"printf hello"}}</action>',
                    "<summary>命令完成。</summary>\n<final_answer>ok</final_answer>",
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

    def test_loop_stops_at_max_iterations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = SequencedProvider(
                [
                    '<summary>继续。</summary>\n'
                    '<action>{"tool":"list_files","args":{}}</action>'
                    for _ in range(20)
                ]
            )

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="offline"),
                provider_factory=lambda name: provider,
            ).run("loop", save_session=False)

            self.assertEqual(run.iterations, 20)
            self.assertIn("maximum iteration limit", run.final_answer)

    def test_iteration_limit_records_last_observation_before_final_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            provider = SequencedProvider(
                [
                    '<summary>继续。</summary>\n'
                    '<action>{"tool":"list_files","args":{}}</action>'
                ]
            )

            run = CodingAgent(
                AgentConfig(workspace_path=root, provider="offline", max_iterations=1),
                provider_factory=lambda name: provider,
            ).run("loop once", save_session=False)

            self.assertEqual(run.iterations, 1)
            self.assertEqual(
                [event.kind for event in run.history],
                ["task", "summary", "action", "observation", "final_answer"],
            )
            self.assertIn("maximum iteration limit", run.final_answer)

    def test_session_log_contains_tagged_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            session_root = Path(tmp) / "sessions"
            provider = SequencedProvider(["<summary>完成。</summary>\n<final_answer>answer</final_answer>"])

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
            self.assertEqual(data["history"][0]["tag"], "<task>task</task>")
            self.assertEqual(data["history"][1]["tag"], "<summary>完成。</summary>")
            self.assertEqual(data["history"][-1]["tag"], "<final_answer>answer</final_answer>")

    def test_session_log_contains_model_call_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            session_root = Path(tmp) / "sessions"
            provider = SequencedProvider(
                [
                    ModelCompletion(
                        text="<summary>完成。</summary>\n<final_answer>answer</final_answer>",
                        usage=TokenUsage(
                            prompt_tokens=9,
                            completion_tokens=4,
                            total_tokens=13,
                        ),
                    )
                ]
            )

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
            self.assertEqual(data["model_calls"][0]["purpose"], "task")
            self.assertEqual(data["model_calls"][0]["usage"]["total_tokens"], 13)
            self.assertEqual(data["runs"][0]["model_calls"][0]["usage"]["prompt_tokens"], 9)

    def test_same_agent_writes_multiple_runs_to_one_session_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            session_root = Path(tmp) / "sessions"
            provider = SequencedProvider(
                [
                    "<summary>完成。</summary>\n<final_answer>first answer</final_answer>",
                    "<summary>完成。</summary>\n<final_answer>second answer</final_answer>",
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

            first = agent.run("first task", save_session=True)
            second = agent.run("second task", save_session=True)

            self.assertEqual(first.session_path, second.session_path)
            session_files = list((session_root / "sessions").glob("*.json"))
            self.assertEqual(len(session_files), 1)
            data = json.loads(session_files[0].read_text(encoding="utf-8"))
            self.assertEqual(data["session_path"], str(session_files[0]))
            self.assertEqual(len(data["runs"]), 2)
            self.assertEqual(data["runs"][0]["prompt"], "first task")
            self.assertEqual(data["runs"][1]["prompt"], "second task")
            self.assertEqual(len(data["model_calls"]), 2)
            second_history_tags = [event["tag"] for event in data["runs"][1]["history"]]
            self.assertIn("<final_answer>first answer</final_answer>", second_history_tags)


if __name__ == "__main__":
    unittest.main()
