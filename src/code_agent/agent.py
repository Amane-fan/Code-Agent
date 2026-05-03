from __future__ import annotations

from dataclasses import replace
from typing import Callable

from code_agent.config import AgentConfig
from code_agent.conversation import CompactionResult, ConversationSession
from code_agent.models import AgentEvent, AgentRun, ModelCallUsage, WorkspaceContext
from code_agent.prompting import build_system_instructions
from code_agent.providers import ModelProvider, make_provider
from code_agent.react import ProviderFactory, run_react_agent
from code_agent.session import SessionStore
from code_agent.skill_selection import SKILL_SELECTOR_SYSTEM_INSTRUCTIONS, select_skills
from code_agent.skills import LoadedSkill, SkillRegistry
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
            workspace_root=config.workspace_root,
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
        initial_history = self.conversation.initial_history()
        loaded_skills, selection_model_calls = self._select_skills(prompt, initial_history)
        task_system_instructions = build_system_instructions(
            tool_registry=self.tool_registry,
            skill_registry=self.skill_registry,
            loaded_skills=loaded_skills,
            workspace_root=self.config.workspace_root,
        )
        provider = self._make_provider(system_instructions=task_system_instructions)
        run = run_react_agent(
            self.config,
            prompt,
            provider_factory=lambda name: provider,
            shell_approval=shell_approval,
            event_logger=event_logger,
            save_session=False,
            initial_history=initial_history,
            session_store=self.session_store,
            skill_registry=self.skill_registry,
            system_instructions=task_system_instructions,
        )
        self.conversation.record_turn(run.history[len(initial_history) :])
        model_calls = [*selection_model_calls, *run.model_calls]
        if self.conversation.should_auto_compact():
            compaction = self.conversation.compact(provider)
            model_calls.extend(compaction.model_calls)
        run = replace(run, model_calls=model_calls)
        if save_session:
            session_path = self.session_store.save(run)
            run = replace(run, session_path=session_path)
        return run

    def compact_memory(
        self,
        *,
        save_session: bool = False,
        usage_logger: Callable[[ModelCallUsage], None] | None = None,
    ) -> CompactionResult:
        provider = self._make_provider()
        result = self.conversation.compact(provider)
        for model_call in result.model_calls:
            if usage_logger is not None:
                usage_logger(model_call)
        if save_session and result.model_calls:
            self.session_store.append_model_calls(result.model_calls)
        return result

    def memory_status(self) -> str:
        return self.conversation.status()

    def clear_memory(self) -> None:
        self.conversation.clear()

    def _make_provider(self, *, system_instructions: str | None = None) -> ModelProvider:
        if self.provider_factory is not None:
            return self.provider_factory(self.config.provider)
        return make_provider(
            self.config.provider,
            system_instructions=system_instructions or self.system_instructions,
        )

    def _select_skills(
        self,
        prompt: str,
        initial_history: list[AgentEvent],
    ) -> tuple[list[LoadedSkill], list[ModelCallUsage]]:
        if self.config.provider.lower().strip() == "offline" or not self.skill_registry.names():
            return [], []

        provider = self._make_provider(system_instructions=SKILL_SELECTOR_SYSTEM_INSTRUCTIONS)
        result = select_skills(
            provider=provider,
            model=self.config.model,
            workspace_context=WorkspaceContext(
                root=self.config.workspace_root,
                prompt="skill selection",
                git_status="",
                files=[],
            ),
            user_prompt=prompt,
            history=initial_history,
            skill_registry=self.skill_registry,
        )
        return result.loaded_skills, result.model_calls
