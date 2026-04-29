from __future__ import annotations

from code_agent.config import AgentConfig
from code_agent.graph import run_agent_graph
from code_agent.models import AgentRun


class CodingAgent:
    """编排上下文收集、模型调用、补丁校验、补丁应用和测试反馈。"""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def run(
        self,
        prompt: str,
        *,
        apply_patch: bool = False,
        run_tests: bool = False,
        test_command: str | None = None,
        allow_unsafe_commands: bool = False,
        save_session: bool = True,
    ) -> AgentRun:
        # 具体节点编排交给 LangGraph，外部接口保持稳定，CLI 和测试无需感知内部改造。
        return run_agent_graph(
            self.config,
            prompt,
            apply_patch=apply_patch,
            run_tests=run_tests,
            test_command=test_command,
            allow_unsafe_commands=allow_unsafe_commands,
            save_session=save_session,
        )
