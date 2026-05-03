from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from pkgutil import iter_modules
from typing import Any, Callable, Protocol, Sequence

from langchain_core.tools import BaseTool

from code_agent.models import ToolResult
from code_agent.skills import SkillRegistry

ShellApproval = Callable[[str], bool]
JsonSchema = dict[str, Any]
Tool = BaseTool


class ToolFactory(Protocol):
    def __call__(self, context: "ToolContext") -> Sequence[BaseTool]:
        ...


@dataclass(frozen=True)
class ToolContext:
    """workspace 绑定工具共享的运行时依赖。"""

    workspace_root: Path
    skill_registry: SkillRegistry | None = None
    shell_approval: ShellApproval | None = None


@dataclass(frozen=True)
class ToolSpec:
    """渲染到审计信息中的工具元数据。"""

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


class ToolRegistry:
    """按名称分发 LangChain BaseTool 调用，并统一返回 ToolResult。"""

    def __init__(self, tools: Sequence[BaseTool]) -> None:
        by_name: dict[str, BaseTool] = {}
        for tool in tools:
            if tool.name in by_name:
                raise ValueError(f"duplicate tool name: {tool.name}")
            by_name[tool.name] = tool
        self._tools = by_name

    @classmethod
    def default(cls, context: ToolContext) -> "ToolRegistry":
        return cls(create_default_tools(context))

    @property
    def tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    @property
    def specs(self) -> list[ToolSpec]:
        return [_tool_spec(tool) for tool in self._tools.values()]

    def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(name, False, error=f"unknown tool: {name}")
        try:
            raw_result = tool.invoke(args)
        except Exception as exc:
            return ToolResult(name, False, error=str(exc), metadata={"args": args})
        return _normalize_tool_result(name, raw_result)


def create_default_tools(context: ToolContext, package_name: str = "code_agent.tools") -> list[BaseTool]:
    tools: list[BaseTool] = []
    for factory in discover_tool_factories(package_name):
        tools.extend(factory(context))
    return tools


def discover_tool_factories(package_name: str = "code_agent.tools") -> list[ToolFactory]:
    """导入工具包模块，返回模块级 create_tools 工厂。"""

    package = import_module(package_name)
    package_paths = getattr(package, "__path__", [])
    factories: list[ToolFactory] = []
    for module_info in iter_modules(package_paths):
        if module_info.name.startswith("_") or module_info.name == "base":
            continue
        module = import_module(f"{package_name}.{module_info.name}")
        factory = getattr(module, "create_tools", None)
        if callable(factory):
            factories.append(factory)
    return factories


def create_workspace_tool_registry(
    workspace_root: Path,
    *,
    skill_registry: SkillRegistry | None = None,
    shell_approval: ShellApproval | None = None,
) -> ToolRegistry:
    """为单个 workspace 创建默认工具注册表。"""

    context = ToolContext(
        workspace_root=workspace_root,
        skill_registry=skill_registry or SkillRegistry.empty(),
        shell_approval=shell_approval,
    )
    return ToolRegistry.default(context)


def _tool_spec(tool: BaseTool) -> ToolSpec:
    return ToolSpec(
        name=tool.name,
        description=tool.description or "",
        parameters_schema=_tool_args_schema(tool),
        returns_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "ok": {"type": "boolean"},
                "output": {"type": "string"},
                "error": {"type": "string"},
                "metadata": {"type": "object"},
            },
        },
    )


def _tool_args_schema(tool: BaseTool) -> JsonSchema:
    schema_object = getattr(tool, "args_schema", None)
    if schema_object is None:
        args = getattr(tool, "args", None)
        if isinstance(args, dict):
            return {"type": "object", "properties": args}
        return {"type": "object", "properties": {}}
    if isinstance(schema_object, dict):
        return schema_object
    model_json_schema = getattr(schema_object, "model_json_schema", None)
    if callable(model_json_schema):
        schema = model_json_schema()
        return schema if isinstance(schema, dict) else {"type": "object", "properties": {}}
    schema = getattr(schema_object, "schema", None)
    if callable(schema):
        legacy_schema = schema()
        return legacy_schema if isinstance(legacy_schema, dict) else {"type": "object"}
    return {"type": "object", "properties": {}}


def _normalize_tool_result(name: str, raw_result: object) -> ToolResult:
    if isinstance(raw_result, ToolResult):
        return raw_result
    if isinstance(raw_result, dict):
        ok = raw_result.get("ok", True)
        output = raw_result.get("output", "")
        error = raw_result.get("error", "")
        metadata = raw_result.get("metadata", {})
        return ToolResult(
            name=str(raw_result.get("name", name)),
            ok=bool(ok),
            output=output if isinstance(output, str) else json.dumps(output, ensure_ascii=False),
            error=error if isinstance(error, str) else str(error),
            metadata=metadata if isinstance(metadata, dict) else {"metadata": metadata},
        )
    return ToolResult(name, True, output=str(raw_result))


def _schema_to_text(schema: JsonSchema) -> str:
    return json.dumps(schema, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
