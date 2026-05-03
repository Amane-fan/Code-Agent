from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from code_agent.models import AgentEvent, ModelCallUsage, ModelCompletion


COMPACTION_SYSTEM_INSTRUCTIONS = (
    "Compress prior conversation JSON events into durable memory for a coding agent. "
    "Preserve user goals, decisions, files changed or inspected, tool outcomes, and "
    "unresolved follow-ups. Do not include secrets. Return one strict JSON event with "
    'role "assistant", type "final_answer", and the memory summary in content.'
)


class CompletionProvider(Protocol):
    @property
    def name(self) -> str:
        ...

    def complete(
        self,
        messages: Sequence[BaseMessage],
        *,
        model: str,
        tools: Sequence[BaseTool] | None = None,
    ) -> ModelCompletion:
        ...


@dataclass(frozen=True)
class CompactionResult:
    compacted: bool
    summary: str
    used_fallback: bool
    source_events: int
    error: str = ""
    model_calls: list[ModelCallUsage] = field(default_factory=list)


@dataclass
class ConversationSession:
    """当前终端窗口内的多轮会话记忆。"""

    workspace_root: Path
    model: str
    max_conversation_chars: int
    recent_turns_to_keep: int
    memory_summary: str = ""
    turns: list[list[AgentEvent]] = field(default_factory=list)

    def initial_history(self) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        if self.memory_summary.strip():
            events.append(AgentEvent(role="system", type="memory", content=self.memory_summary.strip()))
        for turn in self.turns:
            events.extend(turn)
        return events

    def record_turn(self, events: list[AgentEvent]) -> None:
        if events:
            self.turns.append(events)

    def clear(self) -> None:
        self.memory_summary = ""
        self.turns.clear()

    def should_auto_compact(self) -> bool:
        return len(_render_events(self.initial_history())) > self.max_conversation_chars

    def compact(self, provider: CompletionProvider) -> CompactionResult:
        split_index = self._split_index()
        events_to_compact = self._events_to_compact(split_index)
        if not events_to_compact:
            return CompactionResult(
                compacted=False,
                summary=self.memory_summary,
                used_fallback=False,
                source_events=0,
            )

        summary, used_fallback, error, model_calls = self._summarize(provider, events_to_compact)
        self.memory_summary = summary
        self.turns = self.turns[split_index:]
        return CompactionResult(
            compacted=True,
            summary=summary,
            used_fallback=used_fallback,
            source_events=len(events_to_compact),
            error=error,
            model_calls=model_calls,
        )

    def status(self) -> str:
        if self.memory_summary.strip():
            return (
                "Compacted memory:\n"
                f"{self.memory_summary.strip()}\n\n"
                f"Recent complete turns kept: {len(self.turns)}"
            )
        return f"No compacted memory yet. Complete turns in current window: {len(self.turns)}"

    def _split_index(self) -> int:
        keep = max(0, self.recent_turns_to_keep)
        if keep == 0:
            return len(self.turns)
        return max(0, len(self.turns) - keep)

    def _events_to_compact(self, split_index: int) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        if self.memory_summary.strip():
            events.append(AgentEvent(role="system", type="memory", content=self.memory_summary.strip()))
        for turn in self.turns[:split_index]:
            events.extend(turn)
        return events

    def _summarize(
        self,
        provider: CompletionProvider,
        events: list[AgentEvent],
    ) -> tuple[str, bool, str, list[ModelCallUsage]]:
        fallback = _fallback_summary(events)
        if provider.name == "offline":
            return fallback, True, "offline provider does not summarize memory", []
        try:
            response = provider.complete(
                _compression_messages(events),
                model=self.model,
            )
            completion = response if isinstance(response, ModelCompletion) else ModelCompletion(text=str(response))
            model_call = ModelCallUsage(
                provider=provider.name,
                model=self.model,
                purpose="compaction",
                ok=True,
                usage=completion.usage,
                system_instructions=COMPACTION_SYSTEM_INSTRUCTIONS,
            )
            summary = _summary_from_response(completion.text)
            if not summary:
                return fallback, True, "model returned an empty memory summary", [model_call]
            return _truncate(summary, 12_000), False, "", [model_call]
        except Exception as exc:
            return (
                fallback,
                True,
                str(exc),
                [
                    ModelCallUsage(
                        provider=provider.name,
                        model=self.model,
                        purpose="compaction",
                        ok=False,
                        error=str(exc),
                        system_instructions=COMPACTION_SYSTEM_INSTRUCTIONS,
                    )
                ],
            )


def _compression_messages(events: list[AgentEvent]) -> list[BaseMessage]:
    return [
        SystemMessage(content=COMPACTION_SYSTEM_INSTRUCTIONS),
        HumanMessage(content=_render_events(events)),
    ]


def _summary_from_response(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if isinstance(payload, dict) and payload.get("type") == "final_answer":
        content = payload.get("content")
        return content if isinstance(content, str) else ""
    return stripped


def _fallback_summary(events: list[AgentEvent]) -> str:
    lines: list[str] = []
    for event in events:
        if event.type == "memory":
            lines.append(f"Previous memory: {_truncate(event.content, 2_000)}")
        elif event.type == "task":
            lines.append(f"User task: {_truncate(event.content, 1_000)}")
        elif event.type == "summary":
            lines.append(f"Agent summary: {_truncate(event.content, 1_000)}")
        elif event.type == "final_answer":
            lines.append(f"Agent final answer: {_truncate(event.content, 1_000)}")
        elif event.type == "tool_call":
            lines.append(f"Tool call: {_truncate(event.content, 600)}")
        elif event.type == "tool_result":
            lines.append(f"Tool result: {_truncate(event.content, 600)}")
    return _truncate("\n".join(lines), 12_000)


def _render_events(events: list[AgentEvent]) -> str:
    return "\n".join(event.to_json_line() for event in events)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 22].rstrip() + "\n[summary truncated]"
