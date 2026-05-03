from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from typing import Protocol, Sequence

from code_agent.models import AgentEvent, ModelCallUsage, ModelCompletion, WorkspaceContext
from code_agent.skills import LoadedSkill, SkillRegistry


MAX_SELECTED_SKILLS = 3

SKILL_SELECTOR_SYSTEM_INSTRUCTIONS = (
    "You are a skill-selection classifier for Code-Agent. Choose which installed skills, "
    "if any, should be loaded before the main agent handles the user's current task. "
    'Return only strict JSON matching {"skills":["skill_name"]}. Do not include markdown, '
    "XML tags, explanations, or skill names not present in the available list. Select at "
    "most three skills, and return an empty list when no listed skill is relevant."
)


class SkillSelectionProvider(Protocol):
    @property
    def name(self) -> str:
        ...

    def complete(self, prompt: str, context: WorkspaceContext, *, model: str) -> str | ModelCompletion:
        ...


@dataclass(frozen=True)
class SkillSelectionResult:
    loaded_skills: list[LoadedSkill]
    model_calls: list[ModelCallUsage]


def select_skills(
    *,
    provider: SkillSelectionProvider,
    model: str,
    workspace_context: WorkspaceContext,
    user_prompt: str,
    history: Sequence[AgentEvent],
    skill_registry: SkillRegistry,
) -> SkillSelectionResult:
    """Ask a model to select relevant skills without reading workspace files."""

    try:
        response = provider.complete(
            _selection_prompt(
                user_prompt=user_prompt,
                history=history,
                skill_registry=skill_registry,
            ),
            workspace_context,
            model=model,
        )
    except Exception as exc:
        return SkillSelectionResult(
            loaded_skills=[],
            model_calls=[
                ModelCallUsage(
                    provider=provider.name,
                    model=model,
                    purpose="skill_selection",
                    ok=False,
                    error=str(exc),
                    system_instructions=SKILL_SELECTOR_SYSTEM_INSTRUCTIONS,
                )
            ],
        )

    completion = _normalize_completion(response)
    names, error, ok = _parse_selected_skill_names(completion.text, skill_registry)
    loaded_skills = [skill_registry.load(name) for name in names]
    return SkillSelectionResult(
        loaded_skills=loaded_skills,
        model_calls=[
            ModelCallUsage(
                provider=provider.name,
                model=model,
                purpose="skill_selection",
                ok=ok,
                usage=completion.usage,
                error=error,
                system_instructions=SKILL_SELECTOR_SYSTEM_INSTRUCTIONS,
            )
        ],
    )


def _selection_prompt(
    *,
    user_prompt: str,
    history: Sequence[AgentEvent],
    skill_registry: SkillRegistry,
) -> str:
    skills = [
        {"name": item.name, "description": item.description}
        for item in skill_registry.list_metadata()
    ]
    return (
        "Select installed skills for the current task.\n\n"
        "Available skills JSON:\n"
        f"{json.dumps(skills, ensure_ascii=False, sort_keys=True)}\n\n"
        "Current window memory and recent complete turns:\n"
        "<conversation_context>\n"
        f"{_render_history(history)}\n"
        "</conversation_context>\n\n"
        "Current user task:\n"
        f"<task>{escape(user_prompt)}</task>\n\n"
        'Return exactly: {"skills":["skill_name"]}'
    )


def _render_history(history: Sequence[AgentEvent]) -> str:
    if not history:
        return ""
    return "\n".join(event.tag for event in history)


def _parse_selected_skill_names(
    text: str,
    skill_registry: SkillRegistry,
) -> tuple[list[str], str, bool]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], f"invalid skill selection JSON: {exc}", False

    if not isinstance(payload, dict) or set(payload) != {"skills"}:
        return [], 'skill selection must be a JSON object with only the "skills" key', False

    raw_skills = payload.get("skills")
    if not isinstance(raw_skills, list) or not all(isinstance(item, str) for item in raw_skills):
        return [], "skill selection skills must be a list of strings", False

    available = set(skill_registry.names())
    selected: list[str] = []
    ignored_unknown: list[str] = []
    notes: list[str] = []
    for name in raw_skills:
        if name not in available:
            ignored_unknown.append(name)
            continue
        if name in selected:
            continue
        if len(selected) >= MAX_SELECTED_SKILLS:
            continue
        selected.append(name)

    known_unique_count = len({name for name in raw_skills if name in available})
    if known_unique_count > MAX_SELECTED_SKILLS:
        notes.append(f"truncated selected skills to {MAX_SELECTED_SKILLS}")
    if ignored_unknown:
        notes.append(f"ignored unknown skills: {', '.join(sorted(set(ignored_unknown)))}")

    return selected, "; ".join(notes), True


def _normalize_completion(response: str | ModelCompletion) -> ModelCompletion:
    if isinstance(response, ModelCompletion):
        return response
    return ModelCompletion(text=response)
