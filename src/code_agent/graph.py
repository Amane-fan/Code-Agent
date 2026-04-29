from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from code_agent.config import AgentConfig
from code_agent.context import collect_workspace_context
from code_agent.models import AgentRun, ToolResult, WorkspaceContext
from code_agent.patches import PatchTool, extract_unified_diff
from code_agent.providers import make_provider
from code_agent.session import SessionStore
from code_agent.tools import ShellTool, detect_test_command


Route = Literal["check_patch", "apply_patch", "run_tests", "finalize_run"]


class AgentGraphState(TypedDict, total=False):
    """LangGraph 节点之间传递的状态。

    这里保留为 TypedDict，是为了让每个节点只返回自己负责更新的字段，
    更贴近 LangGraph 的状态合并模型。
    """

    prompt: str
    apply_patch: bool
    run_tests: bool
    test_command: str | None
    allow_unsafe_commands: bool
    save_session: bool
    context: WorkspaceContext
    provider_name: str
    response_text: str
    patch: str | None
    patch_check_result: ToolResult | None
    applied: bool
    test_result: ToolResult | None
    agent_run: AgentRun


def build_agent_graph(config: AgentConfig) -> Any:
    """构建 Code Agent 的 LangGraph 工作流。

    MVP 阶段的图是确定性流程：模型不直接选择工具，工具由固定节点按条件调用。
    这样可以保留原来的安全边界，同时让流程结构更清晰。
    """

    graph = StateGraph(AgentGraphState)

    def collect_context(state: AgentGraphState) -> AgentGraphState:
        """收集 workspace 上下文，作为后续模型调用的输入。"""

        context = collect_workspace_context(
            config.workspace_root,
            state["prompt"],
            max_files=config.max_files,
            max_file_bytes=config.max_file_bytes,
            max_context_chars=config.max_context_chars,
        )
        return {"context": context, "applied": False, "test_result": None}

    def call_provider(state: AgentGraphState) -> AgentGraphState:
        """调用模型提供方，生成计划文本和可能的补丁。"""

        provider = make_provider(config.provider)
        response_text = provider.complete(state["prompt"], state["context"], model=config.model)
        return {"provider_name": provider.name, "response_text": response_text}

    def extract_patch(state: AgentGraphState) -> AgentGraphState:
        """从模型回复中提取 unified diff，未提取到时保持为 None。"""

        return {"patch": extract_unified_diff(state["response_text"])}

    def check_patch(state: AgentGraphState) -> AgentGraphState:
        """应用补丁前的安全门：只校验，不修改工作区。"""

        patch = state.get("patch")
        if patch is None:
            return {"patch_check_result": None}
        result = PatchTool(config.workspace_root).check(patch)
        update: AgentGraphState = {"patch_check_result": result}
        if not result.ok:
            update["test_result"] = result
        return update

    def apply_patch_node(state: AgentGraphState) -> AgentGraphState:
        """校验通过后才真正应用补丁。"""

        patch = state.get("patch")
        if patch is None:
            return {"applied": False}
        result = PatchTool(config.workspace_root).apply(patch)
        update: AgentGraphState = {"applied": result.ok}
        if not result.ok:
            update["test_result"] = result
        return update

    def run_tests_node(state: AgentGraphState) -> AgentGraphState:
        """补丁应用成功后运行测试，把测试输出纳入最终结果。"""

        command = state.get("test_command") or detect_test_command(config.workspace_root)
        if command is None:
            return {"test_result": ToolResult("shell.run", False, error="no test command detected")}
        result = ShellTool(config.workspace_root).run(
            command,
            allow_unsafe=state.get("allow_unsafe_commands", False),
        )
        return {"test_result": result}

    def finalize_run(state: AgentGraphState) -> AgentGraphState:
        """把图状态折叠回外部兼容的 AgentRun，并按需保存会话。"""

        context = state["context"]
        run = AgentRun(
            prompt=state["prompt"],
            provider=state.get("provider_name", config.provider),
            model=config.model,
            response_text=state.get("response_text", ""),
            patch=state.get("patch"),
            applied=state.get("applied", False),
            context_files=[file.path for file in context.files],
            test_result=state.get("test_result"),
        )
        if state.get("save_session", True):
            session_path = SessionStore(config.session_dir).save(run)
            run = replace(run, session_path=session_path)
        return {"agent_run": run}

    def route_after_extract(state: AgentGraphState) -> Route:
        """只有用户允许应用补丁且模型确实生成补丁时，才进入补丁校验节点。"""

        if state.get("apply_patch") and state.get("patch"):
            return "check_patch"
        return "finalize_run"

    def route_after_check(state: AgentGraphState) -> Route:
        """补丁校验失败时直接收束，避免继续修改工作区。"""

        result = state.get("patch_check_result")
        if result is not None and result.ok:
            return "apply_patch"
        return "finalize_run"

    def route_after_apply(state: AgentGraphState) -> Route:
        """只有补丁已应用且用户要求测试时才进入测试节点。"""

        if state.get("applied") and state.get("run_tests"):
            return "run_tests"
        return "finalize_run"

    graph.add_node("collect_context", collect_context)
    graph.add_node("call_provider", call_provider)
    graph.add_node("extract_patch", extract_patch)
    graph.add_node("check_patch", check_patch)
    graph.add_node("apply_patch", apply_patch_node)
    graph.add_node("run_tests", run_tests_node)
    graph.add_node("finalize_run", finalize_run)

    graph.add_edge(START, "collect_context")
    graph.add_edge("collect_context", "call_provider")
    graph.add_edge("call_provider", "extract_patch")
    graph.add_conditional_edges(
        "extract_patch",
        route_after_extract,
        {"check_patch": "check_patch", "finalize_run": "finalize_run"},
    )
    graph.add_conditional_edges(
        "check_patch",
        route_after_check,
        {"apply_patch": "apply_patch", "finalize_run": "finalize_run"},
    )
    graph.add_conditional_edges(
        "apply_patch",
        route_after_apply,
        {"run_tests": "run_tests", "finalize_run": "finalize_run"},
    )
    graph.add_edge("run_tests", "finalize_run")
    graph.add_edge("finalize_run", END)

    return graph.compile()


def run_agent_graph(
    config: AgentConfig,
    prompt: str,
    *,
    apply_patch: bool = False,
    run_tests: bool = False,
    test_command: str | None = None,
    allow_unsafe_commands: bool = False,
    save_session: bool = True,
) -> AgentRun:
    """执行 LangGraph 工作流，并返回与旧接口兼容的 AgentRun。"""

    graph = build_agent_graph(config)
    initial_state: AgentGraphState = {
        "prompt": prompt,
        "apply_patch": apply_patch,
        "run_tests": run_tests,
        "test_command": test_command,
        "allow_unsafe_commands": allow_unsafe_commands,
        "save_session": save_session,
    }
    final_state = graph.invoke(initial_state)
    run = final_state.get("agent_run")
    if not isinstance(run, AgentRun):
        raise RuntimeError("LangGraph workflow finished without an AgentRun")
    return run
