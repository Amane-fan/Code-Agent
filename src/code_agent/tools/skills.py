from __future__ import annotations

from typing import Any, ClassVar

from code_agent.models import ToolResult
from code_agent.skills import SkillRegistry
from code_agent.tools.base import JsonSchema, Tool, required_str


class LoadSkillTool(Tool):
    name = "load_skill"
    description = "Load the full instructions for one startup-listed skill by name."
    parameters_schema: ClassVar[JsonSchema] = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name listed at startup."},
        },
        "required": ["name"],
        "additionalProperties": False,
    }
    returns_schema: ClassVar[JsonSchema] = {
        "type": "object",
        "description": (
            "Returns full skill instructions in output and metadata.name plus metadata.path. "
            "On failure, error explains the unknown skill and metadata.available_skills lists "
            "valid names."
        ),
        "properties": {
            "output": {"type": "string", "description": "Full skill instructions."},
            "error": {"type": "string", "description": "Failure reason."},
            "metadata": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                    "available_skills": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        name = required_str(self.name, args, "name")
        skills = self.context.skill_registry or SkillRegistry.empty()
        try:
            loaded = skills.load(name)
        except KeyError:
            return ToolResult(
                self.name,
                False,
                error=f"unknown skill: {name}",
                metadata={"available_skills": skills.names()},
            )
        return ToolResult(
            self.name,
            True,
            output=loaded.content,
            metadata={"name": loaded.metadata.name, "path": str(loaded.path)},
        )
