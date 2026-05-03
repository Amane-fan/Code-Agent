from __future__ import annotations

from html import escape
from importlib.resources import files
from pathlib import Path
from typing import Sequence

from code_agent.skills import LoadedSkill, SkillRegistry
from code_agent.tools import ToolRegistry


BASE_SYSTEM_INSTRUCTIONS = files("code_agent.prompts").joinpath("system.md").read_text(encoding="utf-8")


def build_system_instructions(
    *,
    tool_registry: ToolRegistry,
    skill_registry: SkillRegistry,
    loaded_skills: Sequence[LoadedSkill] | None = None,
    workspace_root: Path | None = None,
    base_instructions: str = BASE_SYSTEM_INSTRUCTIONS,
) -> str:
    """将静态系统规则、工具、skill 元数据和已选 skill 正文合成最终 instructions。"""

    sections = [base_instructions.strip()]
    if workspace_root is not None:
        sections.append(_render_workspace(workspace_root))
    sections.extend(
        [
            _render_tools(tool_registry),
            _render_skills(skill_registry),
            _render_loaded_skills(loaded_skills or []),
        ]
    )
    return "\n\n".join(sections)


def _render_workspace(workspace_root: Path) -> str:
    return f"Target workspace:\n{workspace_root.expanduser().resolve()}"


def _render_tools(tool_registry: ToolRegistry) -> str:
    lines = ["Available tools:"]
    for spec in tool_registry.specs:
        lines.extend(
            [
                f"- {spec.name}: {spec.description}",
                f"  Parameters schema: {spec.args_schema}",
                f"  Returns schema: {spec.returns}",
            ]
        )
    return "\n".join(lines)


def _render_skills(skill_registry: SkillRegistry) -> str:
    lines = [
        "Available skills:",
        (
            "Skill metadata is listed here for visibility. Relevant full skill instructions "
            "are selected before the main task and included in <loaded_skills>. Use "
            "load_skill_resources only for supporting files explicitly referenced by a loaded "
            "skill."
        ),
        "<skills>",
    ]
    metadata = skill_registry.list_metadata()
    if not metadata:
        lines.append("</skills>")
        return "\n".join(lines)

    for skill in metadata:
        lines.extend(
            [
                "<skill>",
                f"  <name>{escape(skill.name)}</name>",
                f"  <description>{escape(skill.description)}</description>",
                "</skill>",
            ]
        )
    lines.append("</skills>")
    return "\n".join(lines)


def _render_loaded_skills(loaded_skills: Sequence[LoadedSkill]) -> str:
    lines = ["Loaded skills for this task:", "<loaded_skills>"]
    for skill in loaded_skills:
        lines.extend(
            [
                "<skill>",
                f"  <name>{escape(skill.metadata.name)}</name>",
                f"  <path>{escape(str(skill.path))}</path>",
                "  <content>",
                skill.content,
                "  </content>",
                "</skill>",
            ]
        )
    lines.append("</loaded_skills>")
    return "\n".join(lines)
