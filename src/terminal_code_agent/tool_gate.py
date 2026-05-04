from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from terminal_code_agent.config import Settings
from terminal_code_agent.schemas import ApprovalRequest, PendingToolCall
from terminal_code_agent.tool_runtime import (
    SecurityError,
    command_is_dangerous,
    ensure_safe_path,
    validate_patch_paths,
)
from terminal_code_agent.tools import TOOL_BY_NAME

RiskRoute = Literal["allowed", "needs_approval", "denied"]

HIGH_RISK_TOOLS = {"apply_patch", "write_file", "run_shell"}


def tool_risk(name: str) -> str:
    if name in HIGH_RISK_TOOLS:
        return "high"
    return "low"


def _precheck_path_args(call: PendingToolCall, settings: Settings, workdir: str) -> None:
    """审批前做路径和危险命令预检，避免把禁止操作交给人工批准。"""

    args = call.args
    if call.name in {"list_files", "search_files", "grep", "read_file", "write_file"}:
        path = args.get("path", ".")
        ensure_safe_path(
            Path(workdir), str(path), check_sensitive=call.name in {"read_file", "write_file"}
        )
    elif call.name == "apply_patch":
        validate_patch_paths(Path(workdir), str(args.get("patch", "")))
    elif call.name == "run_shell" and command_is_dangerous(str(args.get("command", ""))):
        raise SecurityError("安全策略拒绝危险 shell 命令。")
    elif call.name == "load_skill_resource":
        skill_name = str(args.get("skill_name", ""))
        resource_path = str(args.get("resource_path", "SKILL.md"))
        skills_root = settings.skills_dir.resolve()
        skill_root = (skills_root / skill_name).resolve()
        target = (skill_root / resource_path).resolve()
        target.relative_to(skill_root)
        skill_root.relative_to(skills_root)


def evaluate_tool_calls(
    raw_calls: list[dict[str, Any]],
    *,
    settings: Settings,
    workdir: str,
) -> dict[str, Any]:
    """根据工具名、参数和风险等级生成 tool_gate 节点路由。"""

    pending: list[PendingToolCall] = []
    denied: list[dict[str, Any]] = []
    high_risk = False

    for index, raw in enumerate(raw_calls):
        try:
            call = PendingToolCall.model_validate(
                {
                    "id": raw.get("id") or f"call_{index}",
                    "name": raw.get("name"),
                    "args": raw.get("args") or {},
                    "raw": raw,
                }
            )
        except ValidationError as exc:
            denied.append(
                {"name": raw.get("name", "unknown"), "reason": f"工具调用 schema 无效: {exc}"}
            )
            continue

        tool_obj = TOOL_BY_NAME.get(call.name)
        if tool_obj is None:
            denied.append({"name": call.name, "reason": "未知工具，不能执行"})
            continue
        try:
            if tool_obj.args_schema is not None:
                tool_obj.args_schema.model_validate(call.args)
            _precheck_path_args(call, settings, workdir)
        except (ValidationError, SecurityError, ValueError) as exc:
            denied.append({"name": call.name, "reason": str(exc), "id": call.id})
            continue

        pending.append(call)
        high_risk = high_risk or tool_risk(call.name) == "high"

    if denied:
        return {
            "tool_gate_route": "denied",
            "denied_tool_calls": denied,
            "approved_tool_calls": [],
            "approval_request": {},
        }

    if high_risk:
        risk = "将修改工作目录中的文件或执行 shell 命令"
        request = ApprovalRequest(
            question="是否允许执行以下工具调用？",
            tool_calls=pending,
            risk=risk,
        )
        return {
            "tool_gate_route": "needs_approval",
            "approved_tool_calls": [],
            "approval_request": request.model_dump(),
        }

    return {
        "tool_gate_route": "allowed",
        "approved_tool_calls": [call.model_dump() for call in pending],
        "approval_request": {},
        "denied_tool_calls": [],
    }
