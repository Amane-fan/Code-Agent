from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from code_agent.agent import CodingAgent
from code_agent.config import AgentConfig
from code_agent.models import WorkspaceContext


class SequencedProvider:
    name = "fake"

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def complete(self, prompt: str, context: WorkspaceContext, *, model: str) -> str:
        self.prompts.append(prompt)
        if not self.responses:
            raise AssertionError("provider called too many times")
        return self.responses.pop(0)


class ReactLoopTests(unittest.TestCase):
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

    def test_each_run_has_independent_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_provider = SequencedProvider(["<summary>完成。</summary>\n<final_answer>first</final_answer>"])
            second_provider = SequencedProvider(["<summary>完成。</summary>\n<final_answer>second</final_answer>"])
            config = AgentConfig(workspace_path=root, provider="offline")

            CodingAgent(config, provider_factory=lambda name: first_provider).run(
                "first task",
                save_session=False,
            )
            CodingAgent(config, provider_factory=lambda name: second_provider).run(
                "second task",
                save_session=False,
            )

            self.assertIn("<task>first task</task>", first_provider.prompts[0])
            self.assertIn("<task>second task</task>", second_provider.prompts[0])
            self.assertNotIn("first task", second_provider.prompts[0])

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


if __name__ == "__main__":
    unittest.main()
