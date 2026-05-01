from __future__ import annotations

from importlib.resources import files

from code_agent.skills import SkillRegistry
from code_agent.tools import ToolRegistry


BASE_SYSTEM_INSTRUCTIONS = files("code_agent.prompts").joinpath("system.md").read_text(encoding="utf-8")


def build_system_instructions(
    *,
    tool_registry: ToolRegistry,
    skill_registry: SkillRegistry,
    base_instructions: str = BASE_SYSTEM_INSTRUCTIONS,
) -> str:
    """将静态系统规则与启动时发现的工具、skill 元数据合成最终 instructions。"""

    return "\n\n".join(
        [
            base_instructions.strip(),
            _render_tools(tool_registry),
            _render_skills(skill_registry),
        ]
    )


def _render_tools(tool_registry: ToolRegistry) -> str:
    lines = ["Available tools:"]
    for spec in tool_registry.specs:
        lines.extend(
            [
                f"- {spec.name}: {spec.description}",
                f"  Call args: {spec.args_schema}",
                f"  Returns: {spec.returns}",
            ]
        )
    return "\n".join(lines)


def _render_skills(skill_registry: SkillRegistry) -> str:
    lines = [
        "Available skills:",
        (
            "Only skill metadata is loaded at startup. If a listed skill is relevant, "
            'call load_skill with {"name":"skill_name"} and wait for the observation '
            "before relying on the full instructions."
        ),
    ]
    metadata = skill_registry.list_metadata()
    if not metadata:
        lines.append("- No skills are available.")
        return "\n".join(lines)

    for skill in metadata:
        lines.append(f"- {skill.name}: {skill.description}")
    return "\n".join(lines)
