from __future__ import annotations

import inspect
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from pkgutil import iter_modules
from typing import Any, Callable, ClassVar, Sequence

from code_agent.models import ToolResult
from code_agent.skills import SkillRegistry

ShellApproval = Callable[[str], bool]
JsonSchema = dict[str, Any]
ToolClass = type["Tool"]
_TOOL_CLASSES: list[ToolClass] = []


@dataclass(frozen=True)
class ToolContext:
    """workspace 绑定工具共享的运行时依赖。"""

    workspace_root: Path
    skill_registry: SkillRegistry | None = None
    shell_approval: ShellApproval | None = None


@dataclass(frozen=True)
class ToolSpec:
    """渲染到模型 instructions 中的工具元数据。"""

    name: str
    description: str
    parameters_schema: JsonSchema
    returns_schema: JsonSchema

    @property
    def args_schema(self) -> str:
        return _schema_to_text(self.parameters_schema)

    @property
    def returns(self) -> str:
        return _schema_to_text(self.returns_schema)


class Tool(ABC):
    """所有可被模型调用的本地工具的基类。"""

    name: ClassVar[str]
    description: ClassVar[str]
    parameters_schema: ClassVar[JsonSchema]
    returns_schema: ClassVar[JsonSchema]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if inspect.isabstract(cls):
            return
        if not cls.__module__.startswith("code_agent.tools."):
            return
        if not getattr(cls, "name", None):
            return
        _TOOL_CLASSES.append(cls)

    def __init__(self, context: ToolContext) -> None:
        self.context = context

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters_schema=self.parameters_schema,
            returns_schema=self.returns_schema,
        )

    @abstractmethod
    def run(self, args: dict[str, Any]) -> ToolResult:
        """使用模型提供的参数执行工具。"""


class ToolRegistry:
    """按名称分发工具调用，并暴露启动时渲染的工具元数据。"""

    def __init__(self, tools: Sequence[Tool]) -> None:
        by_name: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in by_name:
                raise ValueError(f"duplicate tool name: {tool.name}")
            by_name[tool.name] = tool
        self._tools = by_name

    @classmethod
    def default(cls, context: ToolContext) -> "ToolRegistry":
        tools = [tool_class(context) for tool_class in discover_tool_classes()]
        return cls(tools)

    @property
    def specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self._tools.values()]

    def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(name, False, error=f"unknown tool: {name}")
        try:
            return tool.run(args)
        except ValueError as exc:
            return ToolResult(name, False, error=str(exc), metadata={"args": args})


def discover_tool_classes(package_name: str = "code_agent.tools") -> list[ToolClass]:
    """导入工具包模块，返回包内的 Tool 子类。"""

    _import_tool_modules(package_name)
    discovered: dict[str, ToolClass] = {}
    for tool_class in _TOOL_CLASSES:
        if not tool_class.__module__.startswith(f"{package_name}."):
            continue
        discovered[f"{tool_class.__module__}.{tool_class.__qualname__}"] = tool_class
    return list(discovered.values())


def create_workspace_tool_registry(
    workspace_root: Path,
    *,
    skill_registry: SkillRegistry | None = None,
    shell_approval: ShellApproval | None = None,
) -> ToolRegistry:
    """为单个 workspace 创建默认的自动发现工具注册表。"""

    context = ToolContext(
        workspace_root=workspace_root,
        skill_registry=skill_registry or SkillRegistry.empty(),
        shell_approval=shell_approval,
    )
    return ToolRegistry.default(context)


def _import_tool_modules(package_name: str) -> None:
    package = import_module(package_name)
    package_paths = getattr(package, "__path__", [])
    for module in iter_modules(package_paths):
        if module.name.startswith("_") or module.name == "base":
            continue
        import_module(f"{package_name}.{module.name}")


def _schema_to_text(schema: JsonSchema) -> str:
    return json.dumps(schema, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def required_str(tool: str, args: dict[str, Any], name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str):
        raise ValueError(f"{tool}.{name} must be a string")
    return value


def reject_args(tool: str, args: dict[str, Any]) -> None:
    if args:
        raise ValueError(f"{tool} does not accept arguments")
