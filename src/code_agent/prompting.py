from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Sequence

from langchain_core.prompts import PromptTemplate

from code_agent.skills import LoadedSkill, SkillRegistry
from code_agent.tools import ToolRegistry


BASE_SYSTEM_TEMPLATE = files("code_agent.prompts").joinpath("system.md").read_text(
    encoding="utf-8"
)

EVENT_SCHEMA: dict[str, object] = {
    "role": "assistant",
    "type": "final_answer",
    "content": "Plain final answer text for the user.",
}

SUMMARY_EVENT_SCHEMA: dict[str, object] = {
    "role": "assistant",
    "type": "summary",
    "content": "Brief public summary of the next step.",
}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


BASE_SYSTEM_INSTRUCTIONS = PromptTemplate.from_template(BASE_SYSTEM_TEMPLATE).format(
    workspace_root="",
    tool_catalog="[]",
    skill_catalog="[]",
    loaded_skills="[]",
    event_schema=_json(EVENT_SCHEMA),
    summary_event_schema=_json(SUMMARY_EVENT_SCHEMA),
)


def build_system_instructions(
    *,
    tool_registry: ToolRegistry,
    skill_registry: SkillRegistry,
    loaded_skills: Sequence[LoadedSkill] | None = None,
    workspace_root: Path | None = None,
    base_instructions: str = BASE_SYSTEM_TEMPLATE,
) -> str:
    """将系统模板、工具、skill 元数据和已选 skill 正文合成最终 instructions。"""

    template = PromptTemplate.from_template(base_instructions)
    return template.format(
        workspace_root=str(workspace_root.expanduser().resolve()) if workspace_root else "",
        tool_catalog=_render_tools(tool_registry),
        skill_catalog=_render_skills(skill_registry),
        loaded_skills=_render_loaded_skills(loaded_skills or []),
        event_schema=_json(EVENT_SCHEMA),
        summary_event_schema=_json(SUMMARY_EVENT_SCHEMA),
    ).strip()


def _render_tools(tool_registry: ToolRegistry) -> str:
    tools = [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters_schema": spec.parameters_schema,
        }
        for spec in tool_registry.specs
    ]
    return _json(tools)


def _render_skills(skill_registry: SkillRegistry) -> str:
    skills = [
        {"name": item.name, "description": item.description}
        for item in skill_registry.list_metadata()
    ]
    return _json(skills)

def _render_loaded_skills(loaded_skills: Sequence[LoadedSkill]) -> str:
    skills = [
        {
            "name": skill.metadata.name,
            "path": str(skill.path),
            "content": skill.content,
        }
        for skill in loaded_skills
    ]
    return _json(skills)
