from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from code_agent.models import ToolResult
from code_agent.security import redact_secrets
from code_agent.skills import SkillRegistry
from code_agent.tools.base import ToolContext


MAX_RESOURCE_FILE_BYTES = 24_000
MAX_RESOURCE_OUTPUT_BYTES = 80_000
RESOURCE_PREFIXES = ("references/", "resources/")


@dataclass(frozen=True)
class _ResolvedResource:
    requested_path: str
    path: Path


def create_tools(context: ToolContext) -> list[BaseTool]:
    skills = context.skill_registry or SkillRegistry.empty()

    @tool("load_skill_resources")
    def load_skill_resources(name: str, paths: list[str]) -> ToolResult:
        """Load UTF-8 supporting resource files for a skill selected in this task."""

        try:
            loaded = skills.load(name)
        except KeyError:
            return ToolResult(
                "load_skill_resources",
                False,
                error=f"unknown skill: {name}",
                metadata={"available_skills": skills.names()},
            )

        resolved, error = _resolve_resources(loaded.path.parent, paths)
        if error:
            return ToolResult(
                "load_skill_resources",
                False,
                error=error,
                metadata={"name": name, "paths": paths},
            )

        output, error = _read_resources(resolved)
        if error:
            return ToolResult(
                "load_skill_resources",
                False,
                error=error,
                metadata={"name": name, "paths": paths},
            )

        return ToolResult(
            "load_skill_resources",
            True,
            output=output,
            metadata={"name": loaded.metadata.name, "paths": paths},
        )

    return [load_skill_resources]


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
