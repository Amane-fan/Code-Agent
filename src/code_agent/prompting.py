from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from code_agent.skills import SkillRegistry
from code_agent.tools import ToolRegistry


BASE_SYSTEM_INSTRUCTIONS = files("code_agent.prompts").joinpath("system.md").read_text(encoding="utf-8")


def build_system_instructions(
    *,
    tool_registry: ToolRegistry,
    skill_registry: SkillRegistry,
    workspace_root: Path | None = None,
    base_instructions: str = BASE_SYSTEM_INSTRUCTIONS,
) -> str:
    """将静态系统规则与启动时发现的工具、skill 元数据合成最终 instructions。"""

    sections = [base_instructions.strip()]
    if workspace_root is not None:
        sections.append(_render_workspace(workspace_root))
    sections.extend([_render_tools(tool_registry), _render_skills(skill_registry)])
    return "\n\n".join(sections)


def _render_workspace(workspace_root: Path) -> str:
    return f"Target workspace:\n{workspace_root.expanduser().resolve()}"


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
