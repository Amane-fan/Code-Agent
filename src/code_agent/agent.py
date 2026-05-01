from __future__ import annotations

from typing import Callable

from code_agent.config import AgentConfig
from code_agent.conversation import CompactionResult, ConversationSession
from code_agent.models import AgentEvent, AgentRun
from code_agent.prompting import build_system_instructions
from code_agent.providers import ModelProvider, make_provider
from code_agent.react import ProviderFactory, run_react_agent
from code_agent.session import SessionStore
from code_agent.skills import SkillRegistry
from code_agent.tools import create_workspace_tool_registry


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
        self.session_store = SessionStore(config.session_dir)
        self.skill_registry = SkillRegistry.from_directory(config.skills_root)
        self.tool_registry = create_workspace_tool_registry(
            config.workspace_root,
            skill_registry=self.skill_registry,
        )
        self.system_instructions = build_system_instructions(
            tool_registry=self.tool_registry,
            skill_registry=self.skill_registry,
        )
        self.conversation = ConversationSession(
            workspace_root=config.workspace_root,
            model=config.model,
            max_conversation_chars=config.max_conversation_chars,
            recent_turns_to_keep=config.recent_turns_to_keep,
        )

    def run(
        self,
        prompt: str,
        *,
        shell_approval: ShellApproval | None = None,
        event_logger: EventLogger | None = None,
        save_session: bool = True,
    ) -> AgentRun:
        provider = self._make_provider()
        initial_history = self.conversation.initial_history()
        run = run_react_agent(
            self.config,
            prompt,
            provider_factory=lambda name: provider,
            shell_approval=shell_approval,
            event_logger=event_logger,
            save_session=save_session,
            initial_history=initial_history,
            session_store=self.session_store,
            skill_registry=self.skill_registry,
        )
        self.conversation.record_turn(run.history[len(initial_history) :])
        if self.conversation.should_auto_compact():
            self.conversation.compact(provider)
        return run

    def compact_memory(self) -> CompactionResult:
        provider = self._make_provider()
        return self.conversation.compact(provider)

    def memory_status(self) -> str:
        return self.conversation.status()

    def clear_memory(self) -> None:
        self.conversation.clear()

    def _make_provider(self) -> ModelProvider:
        if self.provider_factory is not None:
            return self.provider_factory(self.config.provider)
        return make_provider(
            self.config.provider,
            system_instructions=self.system_instructions,
        )
