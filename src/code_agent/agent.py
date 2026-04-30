from __future__ import annotations

from typing import Callable

from code_agent.config import AgentConfig
from code_agent.models import AgentEvent, AgentRun
from code_agent.providers import make_provider
from code_agent.react import ProviderFactory, run_react_agent


ShellApproval = Callable[[str], bool]
EventLogger = Callable[[AgentEvent], None]


class CodingAgent:
    """执行单任务 ReAct 循环，并把工具 observation 回灌给模型。"""

    def __init__(
        self,
        config: AgentConfig,
        *,
        provider_factory: ProviderFactory | None = None,
    ) -> None:
        self.config = config
        self.provider_factory = provider_factory

    def run(
        self,
        prompt: str,
        *,
        shell_approval: ShellApproval | None = None,
        event_logger: EventLogger | None = None,
        save_session: bool = True,
    ) -> AgentRun:
        return run_react_agent(
            self.config,
            prompt,
            provider_factory=self.provider_factory or make_provider,
            shell_approval=shell_approval,
            event_logger=event_logger,
            save_session=save_session,
        )
