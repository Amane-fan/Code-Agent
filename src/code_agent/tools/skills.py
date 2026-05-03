from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from code_agent.models import ToolResult
from code_agent.security import redact_secrets
from code_agent.skills import SkillRegistry
from code_agent.tools.base import JsonSchema, Tool, required_str


MAX_RESOURCE_FILE_BYTES = 24_000
MAX_RESOURCE_OUTPUT_BYTES = 80_000
RESOURCE_PREFIXES = ("references/", "resources/")


@dataclass(frozen=True)
class _ResolvedResource:
    requested_path: str
    path: Path


class LoadSkillResourcesTool(Tool):
    name = "load_skill_resources"
    description = (
        "Load UTF-8 supporting resource files from references/ or resources/ under an "
        "installed skill."
    )
    parameters_schema: ClassVar[JsonSchema] = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Installed skill name."},
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Skill-relative paths under references/ or resources/, such as "
                    "references/guide.md."
                ),
            },
        },
        "required": ["name", "paths"],
        "additionalProperties": False,
    }
    returns_schema: ClassVar[JsonSchema] = {
        "type": "object",
        "description": (
            "Returns requested resource text in order, with a title before each file. On any "
            "failure, ok is false and no partial output is returned."
        ),
        "properties": {
            "output": {
                "type": "string",
                "description": "Secret-redacted UTF-8 resource contents with file titles.",
            },
            "error": {"type": "string", "description": "Failure reason."},
            "metadata": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "paths": {"type": "array", "items": {"type": "string"}},
                    "available_skills": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        name = required_str(self.name, args, "name")
        paths = _required_str_list(self.name, args, "paths")
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

        resolved, error = _resolve_resources(loaded.path.parent, paths)
        if error:
            return ToolResult(self.name, False, error=error, metadata={"name": name, "paths": paths})

        output, error = _read_resources(resolved)
        if error:
            return ToolResult(self.name, False, error=error, metadata={"name": name, "paths": paths})

        return ToolResult(
            self.name,
            True,
            output=output,
            metadata={"name": loaded.metadata.name, "paths": paths},
        )


def _required_str_list(tool: str, args: dict[str, Any], name: str) -> list[str]:
    value = args.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{tool}.{name} must be a list of strings")
    return value


def _resolve_resources(skill_root: Path, paths: list[str]) -> tuple[list[_ResolvedResource], str]:
    resolved: list[_ResolvedResource] = []
    root = skill_root.resolve()
    for requested_path in paths:
        resource_path = Path(requested_path)
        if resource_path.is_absolute():
            return [], f"resource path must be relative: {requested_path}"
        if any(part == ".." for part in resource_path.parts):
            return [], f"resource path may not contain '..': {requested_path}"
        if resource_path.name == "SKILL.md":
            return [], f"refusing to load SKILL.md as a resource: {requested_path}"
        if not requested_path.startswith(RESOURCE_PREFIXES):
            return [], (
                "resource path must start with references/ or resources/: "
                f"{requested_path}"
            )

        candidate = (root / resource_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return [], f"resource path escapes skill directory: {requested_path}"
        if candidate.is_dir():
            return [], f"resource path is a directory: {requested_path}"
        if not candidate.exists():
            return [], f"resource file does not exist: {requested_path}"
        if not candidate.is_file():
            return [], f"resource path is not a file: {requested_path}"
        resolved.append(_ResolvedResource(requested_path=requested_path, path=candidate))
    return resolved, ""


def _read_resources(resources: list[_ResolvedResource]) -> tuple[str, str]:
    sections: list[str] = []
    for resource in resources:
        try:
            data = resource.path.read_bytes()
        except OSError as exc:
            return "", f"failed to read resource {resource.requested_path}: {exc}"
        if len(data) > MAX_RESOURCE_FILE_BYTES:
            return "", (
                f"resource file exceeds {MAX_RESOURCE_FILE_BYTES} bytes: "
                f"{resource.requested_path}"
            )
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            return "", f"resource file is not valid UTF-8: {resource.requested_path}: {exc}"
        sections.append(f"--- {resource.requested_path} ---\n{redact_secrets(text)}")

    output = "\n\n".join(sections)
    if len(output.encode("utf-8")) > MAX_RESOURCE_OUTPUT_BYTES:
        return "", f"resource output exceeds {MAX_RESOURCE_OUTPUT_BYTES} bytes"
    return output, ""
