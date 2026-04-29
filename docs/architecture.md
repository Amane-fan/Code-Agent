# 架构说明

## 组件

- CLI：解析命令参数并输出 Agent 执行结果。
- 上下文收集器：按任务相关性排序可读仓库文件，并构建模型上下文。
- Provider 层：默认使用 OpenAI 兼容 Responses API 调用，并保留确定性的离线规划模式。
- 工具层：提供安全文件读取、搜索、shell 执行、测试命令检测和补丁应用能力。
- LangGraph 工作流：使用 `StateGraph` 编排上下文收集、模型调用、diff 提取、补丁校验、补丁应用和测试执行。
- 会话存储：将 JSON 运行日志写入 `.code-agent/sessions`。

## 数据流

1. 用户运行 `code-agent ask "task"`。
2. LangGraph 工作流从 `collect_context` 节点开始。
3. `collect_context` 读取非敏感仓库文件和 Git 状态。
4. `call_provider` 调用配置的 Provider；默认 Provider 要求模型名和 API Key 来自仓库
   `.env`，Base URL 优先读取 `.env`，然后生成计划文本，并尽可能返回 `diff` fenced block。
5. `extract_patch` 从模型回复中解析 unified diff。
6. 条件边决定是否进入 `check_patch`、`apply_patch` 和 `run_tests`。
7. `check_patch` 使用 `git apply --check` 校验 unified diff。
8. 如果设置了 `--apply` 且校验通过，`apply_patch` 会应用补丁。
9. 如果设置了 `--test`，`run_tests` 会执行自动检测或用户指定的测试命令。
   对于包含 `tests/` 目录的 Python 项目，默认测试命令是
   `python -m unittest discover -s tests`。
10. `finalize_run` 将图状态转换回 `AgentRun`，并在未设置 `--no-session` 时保存 JSON 会话日志。

## 图结构

```text
START
  -> collect_context
  -> call_provider
  -> extract_patch
  -> check_patch, when --apply and patch exists
  -> apply_patch, when patch check passed
  -> run_tests, when patch applied and --test is enabled
  -> finalize_run
  -> END
```

## 扩展方向

- 使用 Rich 或 Typer 增强交互式 CLI/TUI。
- 为大型仓库加入 Embedding 检索和符号索引。
- 在现有工具返回协议之上接入 MCP 风格的外部工具。
- 增加多 Agent 角色，例如 planner、coder、reviewer、tester。
