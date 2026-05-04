import contextlib
import contextvars
import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from terminal_code_agent.config import Settings
from terminal_code_agent.tool_runtime import (
    SecurityError,
    command_is_dangerous,
    ensure_safe_path,
    error_result,
    is_binary_file,
    iter_files,
    ok_result,
    parse_tool_result,
    read_text_file,
    relative_to_root,
    run_subprocess,
    truncate_text,
    validate_patch_paths,
    with_line_numbers,
)


@dataclass(frozen=True)
class ToolExecutionContext:
    workdir: Path
    settings: Settings


_CURRENT_CONTEXT: contextvars.ContextVar[ToolExecutionContext | None] = contextvars.ContextVar(
    "terminal_code_agent_tool_context", default=None
)


@contextlib.contextmanager
def tool_context(workdir: str | Path, settings: Settings):
    """为 LangChain 工具注入当前工作目录。

    当前 LangChain 版本没有暴露开发文档中的 ToolRuntime 类型；这里用 ContextVar
    只在单次工具执行期间传递 workdir，不保存会话状态。
    """

    token = _CURRENT_CONTEXT.set(ToolExecutionContext(Path(workdir).resolve(), settings))
    try:
        yield
    finally:
        _CURRENT_CONTEXT.reset(token)


def _context() -> ToolExecutionContext:
    ctx = _CURRENT_CONTEXT.get()
    if ctx is None:
        raise RuntimeError("工具执行上下文不存在，请通过 tool_context() 调用工具。")
    return ctx


class ListFilesInput(BaseModel):
    path: str = Field(default=".", description="相对于工作目录的目录路径")
    max_depth: int = Field(default=2, ge=0, le=8, description="最大递归深度")
    include_hidden: bool = Field(default=False, description="是否包含隐藏文件")
    max_entries: int = Field(default=200, ge=1, le=1000, description="最多返回条目数")


class SearchFilesInput(BaseModel):
    pattern: str = Field(description="文件名匹配模式，支持 glob，例如 '*.py' 或 '*agent*'")
    path: str = Field(default=".", description="相对于工作目录的搜索起点")
    include_hidden: bool = Field(default=False, description="是否包含隐藏文件")
    max_results: int = Field(default=100, ge=1, le=1000, description="最多返回结果数")


class GrepInput(BaseModel):
    pattern: str = Field(description="要搜索的文本或正则表达式")
    path: str = Field(default=".", description="相对于工作目录的搜索起点")
    glob: str = Field(default="*", description="文件 glob 过滤，例如 '*.py'")
    case_sensitive: bool = Field(default=True, description="是否大小写敏感")
    regex: bool = Field(default=False, description="是否按正则表达式搜索")
    context_lines: int = Field(default=0, ge=0, le=5, description="返回命中前后的上下文行数")
    max_results: int = Field(default=100, ge=1, le=1000, description="最多返回命中数")


class ReadFileInput(BaseModel):
    path: str = Field(description="相对于工作目录的文件路径")
    start_line: int | None = Field(default=None, ge=1, description="起始行号，1-based")
    end_line: int | None = Field(default=None, ge=1, description="结束行号，包含该行")
    max_chars: int = Field(default=20000, ge=100, le=100000, description="最多返回字符数")


class ApplyPatchInput(BaseModel):
    patch: str = Field(description="unified diff 格式的 patch 内容")


class WriteFileInput(BaseModel):
    path: str = Field(description="相对于工作目录的文件路径")
    content: str = Field(description="要写入的文件内容")
    mode: Literal["overwrite", "append", "create_only"] = Field(default="create_only")
    create_parents: bool = Field(default=True)


class RunShellInput(BaseModel):
    command: str = Field(description="要执行的 shell 命令")
    timeout_seconds: int | None = Field(default=None, ge=1, le=600, description="超时时间")


class LoadSkillResourceInput(BaseModel):
    skill_name: str = Field(description="skill 名称，对应 skills/<skill_name>")
    resource_path: str = Field(default="SKILL.md", description="skill 内部资源相对路径")
    max_chars: int = Field(default=20000, ge=100, le=100000, description="最多返回字符数")


@tool(args_schema=ListFilesInput)
def list_files(
    path: str = ".",
    max_depth: int = 2,
    include_hidden: bool = False,
    max_entries: int = 200,
) -> str:
    """查看工作目录中的目录结构。

    返回 JSON 字符串。成功时包含相对路径、类型和文件大小；失败时包含错误类型和修复建议。
    """

    ctx = _context()
    try:
        start = ensure_safe_path(ctx.workdir, path, check_sensitive=False)
        if not start.exists() or not start.is_dir():
            return error_result(
                "list_files", "retryable_error", f"目录不存在: {path}", hint="请检查路径。"
            )
        entries: list[dict[str, Any]] = []
        truncated = False
        root_depth = len(start.relative_to(ctx.workdir).parts)
        for item in sorted(start.rglob("*")):
            rel = relative_to_root(ctx.workdir, item)
            if not include_hidden and any(part.startswith(".") for part in Path(rel).parts):
                continue
            if any(
                part
                in {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache"}
                for part in Path(rel).parts
            ):
                continue
            depth = len(item.relative_to(ctx.workdir).parts) - root_depth
            if depth > max_depth:
                continue
            if len(entries) >= max_entries:
                truncated = True
                break
            entry: dict[str, Any] = {"path": rel, "type": "dir" if item.is_dir() else "file"}
            if item.is_file():
                entry["size"] = item.stat().st_size
            entries.append(entry)
        return ok_result(
            "list_files", {"root": path, "entries": entries}, metadata={"truncated": truncated}
        )
    except SecurityError as exc:
        return error_result("list_files", "fatal_error", str(exc))
    except OSError as exc:
        return error_result(
            "list_files", "retryable_error", str(exc), hint="请确认目录权限和路径。"
        )


@tool(args_schema=SearchFilesInput)
def search_files(
    pattern: str,
    path: str = ".",
    include_hidden: bool = False,
    max_results: int = 100,
) -> str:
    """按文件名 glob 搜索工作目录中的文件。

    返回 JSON 字符串。成功时包含匹配到的相对路径列表。
    """

    ctx = _context()
    try:
        start = ensure_safe_path(ctx.workdir, path, check_sensitive=False)
        if not start.exists():
            return error_result(
                "search_files", "retryable_error", f"路径不存在: {path}", hint="请先 list_files。"
            )
        matches: list[str] = []
        truncated = False
        for item in iter_files(ctx.workdir, start, include_hidden=include_hidden):
            if item.is_file() and fnmatch.fnmatch(item.name, pattern):
                if len(matches) >= max_results:
                    truncated = True
                    break
                matches.append(relative_to_root(ctx.workdir, item))
        return ok_result(
            "search_files", {"matches": sorted(matches)}, metadata={"truncated": truncated}
        )
    except SecurityError as exc:
        return error_result("search_files", "fatal_error", str(exc))


@tool(args_schema=GrepInput)
def grep(
    pattern: str,
    path: str = ".",
    glob: str = "*",
    case_sensitive: bool = True,
    regex: bool = False,
    context_lines: int = 0,
    max_results: int = 100,
) -> str:
    """按文本或正则表达式搜索工作目录中的文件内容。

    返回 JSON 字符串。成功时包含路径、行号、命中行和上下文。
    """

    ctx = _context()
    try:
        start = ensure_safe_path(ctx.workdir, path, check_sensitive=False)
        flags = 0 if case_sensitive else re.IGNORECASE
        matcher = re.compile(pattern, flags) if regex else None
    except re.error as exc:
        return error_result(
            "grep", "retryable_error", f"正则表达式无效: {exc}", hint="请修正 pattern。"
        )
    except SecurityError as exc:
        return error_result("grep", "fatal_error", str(exc))

    results: list[dict[str, Any]] = []
    skipped: list[str] = []
    try:
        for item in iter_files(ctx.workdir, start):
            if not item.is_file() or not fnmatch.fnmatch(item.name, glob):
                continue
            rel = relative_to_root(ctx.workdir, item)
            if item.stat().st_size > 2 * 1024 * 1024 or is_binary_file(item):
                skipped.append(rel)
                continue
            content = read_text_file(item)
            lines = content.splitlines()
            for index, line in enumerate(lines):
                haystack = line if case_sensitive else line.lower()
                needle = pattern if case_sensitive else pattern.lower()
                matched = bool(matcher.search(line)) if matcher else needle in haystack
                if not matched:
                    continue
                before = lines[max(0, index - context_lines) : index]
                after = lines[index + 1 : index + 1 + context_lines]
                results.append(
                    {
                        "path": rel,
                        "line": index + 1,
                        "content": line,
                        "before": before,
                        "after": after,
                    }
                )
                if len(results) >= max_results:
                    return ok_result(
                        "grep",
                        {"matches": results},
                        metadata={"truncated": True, "skipped": skipped},
                    )
        return ok_result(
            "grep", {"matches": results}, metadata={"truncated": False, "skipped": skipped}
        )
    except OSError as exc:
        return error_result("grep", "retryable_error", str(exc), hint="请检查文件权限。")


@tool(args_schema=ReadFileInput)
def read_file(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    max_chars: int = 20000,
) -> str:
    """读取工作目录中的文本文件。

    返回 JSON 字符串。成功时包含带行号的文件内容；失败时包含错误类型和修复建议。
    """

    ctx = _context()
    try:
        target = ensure_safe_path(ctx.workdir, path)
        if not target.exists() or not target.is_file():
            return error_result(
                "read_file",
                "retryable_error",
                f"文件不存在: {path}",
                hint="请先 search_files 或 list_files。",
            )
        if is_binary_file(target):
            return error_result(
                "read_file",
                "retryable_error",
                f"二进制文件不能读取: {path}",
                hint="请选择文本文件。",
            )
        lines = read_text_file(target).splitlines()
        start = start_line or 1
        end = end_line or len(lines)
        if end < start:
            return error_result("read_file", "retryable_error", "end_line 不能小于 start_line。")
        selected = "\n".join(lines[start - 1 : end])
        numbered = with_line_numbers(selected, start_line=start)
        content, truncated = truncate_text(numbered, max_chars)
        return ok_result(
            "read_file",
            {"path": relative_to_root(ctx.workdir, target), "content": content},
            metadata={
                "truncated": truncated,
                "start_line": start,
                "end_line": min(end, len(lines)),
            },
        )
    except SecurityError as exc:
        return error_result("read_file", "fatal_error", str(exc))
    except OSError as exc:
        return error_result("read_file", "retryable_error", str(exc), hint="请检查文件权限。")


@tool(args_schema=ApplyPatchInput)
def apply_patch(patch: str) -> str:
    """使用 unified diff 修改工作目录中的文件。

    返回 JSON 字符串。成功时包含修改文件列表；patch 冲突返回 retryable_error。
    """

    ctx = _context()
    try:
        changed = validate_patch_paths(ctx.workdir, patch)
    except SecurityError as exc:
        return error_result("apply_patch", "fatal_error", str(exc))
    # subprocess.run 不能直接把 patch 喂给 list 命令时复用辅助函数，这里单独执行以保留 stdin。
    try:
        import subprocess

        check_process = subprocess.run(
            ["git", "apply", "--check", "-"],
            cwd=ctx.workdir,
            input=patch,
            text=True,
            capture_output=True,
            timeout=ctx.settings.shell_timeout_seconds,
            check=False,
        )
        if check_process.returncode != 0:
            stderr, truncated = truncate_text(
                check_process.stderr, ctx.settings.max_context_chars_per_tool_result
            )
            return error_result(
                "apply_patch",
                "retryable_error",
                "patch 校验失败",
                hint="请重新读取相关文件后生成可应用的 patch。",
                metadata={"stderr": stderr, "truncated": truncated},
            )
        apply_process = subprocess.run(
            ["git", "apply", "-"],
            cwd=ctx.workdir,
            input=patch,
            text=True,
            capture_output=True,
            timeout=ctx.settings.shell_timeout_seconds,
            check=False,
        )
        if apply_process.returncode != 0:
            stderr, truncated = truncate_text(
                apply_process.stderr, ctx.settings.max_context_chars_per_tool_result
            )
            return error_result(
                "apply_patch",
                "retryable_error",
                "patch 应用失败",
                metadata={"stderr": stderr, "truncated": truncated},
            )
        return ok_result(
            "apply_patch", {"changed_files": changed}, metadata={"changed_files": changed}
        )
    except subprocess.TimeoutExpired:
        return error_result("apply_patch", "retryable_error", "patch 命令超时")


@tool(args_schema=WriteFileInput)
def write_file(
    path: str,
    content: str,
    mode: Literal["overwrite", "append", "create_only"] = "create_only",
    create_parents: bool = True,
) -> str:
    """创建、覆盖或追加写入工作目录中的文本文件。

    返回 JSON 字符串。成功时包含路径、模式和写入字节数。
    """

    ctx = _context()
    try:
        target = ensure_safe_path(ctx.workdir, path)
        if mode == "create_only" and target.exists():
            return error_result(
                "write_file",
                "retryable_error",
                f"文件已存在: {path}",
                hint="如需覆盖请使用 overwrite。",
            )
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        elif not target.parent.exists():
            return error_result("write_file", "retryable_error", f"父目录不存在: {target.parent}")
        if mode == "append":
            with target.open("a", encoding="utf-8") as handle:
                handle.write(content)
        else:
            target.write_text(content, encoding="utf-8")
        return ok_result(
            "write_file",
            {
                "path": relative_to_root(ctx.workdir, target),
                "mode": mode,
                "bytes": len(content.encode("utf-8")),
            },
            metadata={"changed_files": [relative_to_root(ctx.workdir, target)]},
        )
    except SecurityError as exc:
        return error_result("write_file", "fatal_error", str(exc))
    except OSError as exc:
        return error_result(
            "write_file", "retryable_error", str(exc), hint="请检查文件权限和路径。"
        )


@tool(args_schema=RunShellInput)
def run_shell(command: str, timeout_seconds: int | None = None) -> str:
    """在工作目录下运行 shell 命令。

    返回 JSON 字符串。成功时包含 stdout、stderr 和 exit_code；危险命令直接拒绝。
    """

    ctx = _context()
    if command_is_dangerous(command):
        return error_result("run_shell", "fatal_error", "安全策略拒绝危险命令。")
    timeout = timeout_seconds or ctx.settings.shell_timeout_seconds
    result = run_subprocess(
        command,
        cwd=ctx.workdir,
        timeout_seconds=timeout,
        shell=True,
        max_chars=ctx.settings.max_context_chars_per_tool_result,
    )
    data = {
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "exit_code": result["exit_code"],
    }
    if result["ok"]:
        return ok_result(
            "run_shell", data, metadata={"truncated": result["truncated"], "command": command}
        )
    return error_result(
        "run_shell",
        result["error_type"] or "retryable_error",
        result["message"],
        hint="请根据 stdout/stderr 调整命令。",
        metadata={**data, "truncated": result["truncated"], "command": command},
    )


@tool(args_schema=LoadSkillResourceInput)
def load_skill_resource(
    skill_name: str, resource_path: str = "SKILL.md", max_chars: int = 20000
) -> str:
    """读取 skills/<skill_name> 内部资源。

    返回 JSON 字符串。成功时包含资源文本；路径逃逸或资源不存在会返回错误。
    """

    ctx = _context()
    try:
        skills_root = ctx.settings.skills_dir.resolve()
        skill_root = (skills_root / skill_name).resolve()
        target = (skill_root / resource_path).resolve()
        target.relative_to(skill_root)
        skill_root.relative_to(skills_root)
        if not target.exists() or not target.is_file():
            return error_result(
                "load_skill_resource",
                "retryable_error",
                f"skill 资源不存在: {skill_name}/{resource_path}",
            )
        if is_binary_file(target):
            return error_result(
                "load_skill_resource", "retryable_error", "skill 资源不是文本文件。"
            )
        content, truncated = truncate_text(read_text_file(target), max_chars)
        return ok_result(
            "load_skill_resource",
            {"skill_name": skill_name, "resource_path": resource_path, "content": content},
            metadata={"truncated": truncated},
        )
    except ValueError:
        return error_result("load_skill_resource", "fatal_error", "安全策略拒绝 skill 路径逃逸。")


TOOLS = [
    list_files,
    search_files,
    grep,
    read_file,
    apply_patch,
    write_file,
    run_shell,
    load_skill_resource,
]

TOOL_BY_NAME = {tool_obj.name: tool_obj for tool_obj in TOOLS}


def invoke_tool(name: str, args: dict[str, Any], *, workdir: str | Path, settings: Settings) -> str:
    """测试和图节点共用的工具调用入口。"""

    tool_obj = TOOL_BY_NAME[name]
    with tool_context(workdir, settings):
        return tool_obj.invoke(args)


def summarize_tool_result(raw: str) -> dict[str, Any]:
    """把工具 JSON 结果提炼为观察摘要。"""

    parsed = parse_tool_result(raw)
    data = parsed.data
    summary: dict[str, Any] = {"tool": parsed.tool, "ok": parsed.ok, "message": parsed.message}
    if not parsed.ok:
        summary["error_type"] = parsed.error_type
        if parsed.hint:
            summary["hint"] = parsed.hint
        stderr = str(parsed.metadata.get("stderr") or data.get("stderr") or "")
        stdout = str(parsed.metadata.get("stdout") or data.get("stdout") or "")
        if stderr:
            summary["stderr"] = stderr
        if stdout:
            summary["stdout"] = stdout
    if parsed.tool == "list_files":
        summary["entries"] = len(data.get("entries", []))
    elif parsed.tool == "search_files":
        summary["matches"] = len(data.get("matches", []))
    elif parsed.tool == "grep":
        summary["matches"] = len(data.get("matches", []))
    elif parsed.tool == "read_file":
        summary["path"] = data.get("path")
    elif parsed.tool in {"write_file", "apply_patch"}:
        summary["changed_files"] = parsed.metadata.get("changed_files") or data.get(
            "changed_files", []
        )
    elif parsed.tool == "run_shell":
        summary["exit_code"] = data.get("exit_code") or parsed.metadata.get("exit_code")
    return summary
