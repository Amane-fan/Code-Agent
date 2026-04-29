# 架构说明

## 组件

- CLI：解析顶层启动参数，并提供 `code-agent>` 交互式输入循环。
- 上下文收集器：按任务相关性排序目标 workspace 内的可读文件，并构建模型上下文。
- Provider 层：默认使用 OpenAI 兼容 Responses API 调用，并保留确定性的离线规划模式。
- Prompt 资源：系统 prompt 固定来自 Code-Agent 项目内的 `src/code_agent/prompts/system.md`。
- 工具层：提供安全文件读取、搜索、shell 执行、测试命令检测和补丁应用能力。
- LangGraph 工作流：使用 `StateGraph` 编排上下文收集、模型调用、diff 提取和会话收束。
- 会话存储：将 JSON 运行日志写入 Code-Agent 项目自身的 `.code-agent/sessions`。

## 数据流

1. 用户运行 `code-agent --workspace /path/to/target-project`。
2. CLI 进入交互式循环，等待 `code-agent>` 输入。
3. 用户输入普通文本后，LangGraph 工作流从 `collect_context` 节点开始。
4. `collect_context` 只读取 workspace 内的非敏感文件和 Git 状态。
5. `call_provider` 调用配置的 Provider；默认 Provider 的模型名、API Key 和 Base URL 来自
   Code-Agent 项目 `.env` 或进程环境变量，不读取目标 workspace 的 `.env`。
6. `extract_patch` 从模型回复中解析 unified diff。
7. `finalize_run` 将图状态转换回 `AgentRun`，并在未设置 `--no-session` 时保存 JSON 会话日志。
8. 如果模型生成了 diff，CLI 使用目标 workspace 作为 `cwd` 执行 `git apply --check`。
9. 校验通过后 CLI 询问 `Apply patch? [y/N]`，只有用户确认才应用补丁。

## 图结构

```text
START
  -> collect_context
  -> call_provider
  -> extract_patch
  -> finalize_run
  -> END
```

补丁校验和应用是交互式 CLI 的人为安全门，不在默认图里自动修改 workspace。

## 边界

- `--workspace` 是 Agent 唯一可观察和可修改的目标代码边界。
- `.env`、私钥、`.git`、`.venv`、`node_modules` 等敏感路径不会进入模型上下文。
- 文件工具、shell 工具、补丁校验和补丁应用都以 workspace 根目录为边界。
- Code-Agent 项目自身只提供运行配置、系统 prompt 和会话日志。

## 扩展方向

- 使用 Rich 或 Typer 增强交互式 CLI/TUI。
- 为大型 workspace 加入 Embedding 检索和符号索引。
- 在现有工具返回协议之上接入 MCP 风格的外部工具。
- 增加多 Agent 角色，例如 planner、coder、reviewer、tester。
