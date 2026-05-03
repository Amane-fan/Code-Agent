from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class SkillMetadata:
    """启动时注入上下文的轻量 skill 元数据。"""

    name: str
    description: str


@dataclass(frozen=True)
class LoadedSkill:
    """按需加载后的完整 skill 内容。"""

    metadata: SkillMetadata
    content: str
    path: Path


class SkillRegistry:
    """从 Code-Agent 受控目录加载 SKILL.md 元数据，并按名称读取完整内容。"""

    def __init__(self, skills: Mapping[str, LoadedSkill]) -> None:
        self._skills = dict(skills)

    @classmethod
    def empty(cls) -> SkillRegistry:
        return cls({})

    @classmethod
    def from_loaded(cls, loaded_skills: list[LoadedSkill]) -> SkillRegistry:
        return cls({skill.metadata.name: skill for skill in loaded_skills})

    @classmethod
    def from_directory(cls, root: Path | None) -> SkillRegistry:
        if root is None:
            return cls.empty()

        skills_root = root.expanduser().resolve()
        if not skills_root.exists():
            return cls.empty()
        if not skills_root.is_dir():
            raise ValueError(f"skills path is not a directory: {skills_root}")

        skills: dict[str, LoadedSkill] = {}
        for skill_file in _skill_files(skills_root):
            loaded = _load_skill_file(skill_file)
            name = loaded.metadata.name
            if name in skills:
                raise ValueError(f"duplicate skill name: {name}")
            skills[name] = loaded
        return cls(skills)

    def list_metadata(self) -> list[SkillMetadata]:
        return [self._skills[name].metadata for name in sorted(self._skills)]

    def load(self, name: str) -> LoadedSkill:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise KeyError(name) from exc

    def names(self) -> list[str]:
        return sorted(self._skills)


def _skill_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        skill_file = child / "SKILL.md"
        if skill_file.is_file():
            files.append(skill_file)
    return files


def _load_skill_file(path: Path) -> LoadedSkill:
    content = path.read_text(encoding="utf-8")
    metadata = _parse_metadata(path, content)
    return LoadedSkill(metadata=metadata, content=content, path=path)


def _parse_metadata(path: Path, content: str) -> SkillMetadata:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path}: missing required metadata frontmatter")

    end_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise ValueError(f"{path}: missing required metadata frontmatter")

    metadata: dict[str, str] = {}
    for line in lines[1:end_index]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise ValueError(f"{path}: invalid metadata line: {line}")
        key, value = stripped.split(":", 1)
        metadata[key.strip()] = _unquote(value.strip())

    name = metadata.get("name", "").strip()
    description = metadata.get("description", "").strip()
    if not name or not description:
        raise ValueError(f"{path}: missing required metadata: name and description")
    return SkillMetadata(name=name, description=description)


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
