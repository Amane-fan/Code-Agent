# 架构说明

## 组件

- CLI：解析顶层启动参数，并提供 `code-agent>` 交互式输入循环。
- Conversation Session：保存当前终端窗口内的多轮历史、压缩摘要和近期完整轮次。
- ReAct Runner：为每条用户输入执行一次工具循环，用 `while True` 编排模型调用、工具执行和最终回答。
- Provider 层：默认使用 OpenAI 兼容 Responses API 调用，并保留确定性的离线模式。
- Prompt 资源：系统 prompt 固定来自 Code-Agent 项目内的 `src/code_agent/prompts/system.md`。
- 工具层：提供 `read_file`、`write_file`、`edit_file`、`list_files`、`grep_search`、`run_shell`。
- 会话存储：每个交互窗口创建一份 JSON 日志，并把同一窗口内的多轮运行追加到 `runs` 列表。

## 数据流

1. 用户运行 `code-agent --workspace /path/to/target-project`。
2. CLI 进入交互式循环，等待 `code-agent>` 输入。
3. 用户输入普通文本后，CLI 从 Conversation Session 取出当前窗口记忆和未压缩近期轮次。
4. Runner 在这些历史后追加新的 `<task>`，并把完整标签历史发送给 Provider。
5. Provider 返回 `<summary>` 加 `<action>` 或 `<final_answer>`。
6. 如果返回 `<action>`，Runner 执行工具，把结果作为 `<observation>` 追加到历史，然后继续循环。
7. 如果返回 `<final_answer>`，Runner 把本轮运行写入当前窗口的同一份日志文件，并结束本次任务。
8. 如果窗口历史超过上限，Conversation Session 把旧轮次压缩为 `<memory>`，并保留最近完整轮次。
9. 如果模型连续调用工具超过 20 轮，Runner 生成错误型 `<final_answer>` 并结束。

## 边界

- `--workspace` 是 Agent 唯一可观察和可修改的目标代码边界。
- 初始模型请求不自动包含文件内容；文件内容必须通过工具 observation 进入历史。
- 会话记忆只在当前终端进程内存在，退出后不会自动恢复。
- 会话日志文件会保留同一窗口内的多轮运行；新建 `CodingAgent` 或重新启动 CLI 会创建新的日志文件。
- `<memory>` 是压缩后的对话摘要，只作为模型输入上下文；模型不应自行输出 `<memory>`。
- `.env`、私钥、`.git`、`.venv`、`node_modules` 等敏感路径不会被文件工具读取或写入。
- `run_shell` 以 workspace 为 `cwd`，每次执行前都需要用户确认。
- Code-Agent 项目自身只提供运行配置、系统 prompt 和会话日志。

## 扩展方向

- 使用 Rich 或 Typer 增强交互式 CLI/TUI。
- 为大型 workspace 加入 Embedding 检索和符号索引。
- 在现有工具返回协议之上接入 MCP 风格的外部工具。
- 增加可恢复会话、长期偏好记忆或多 Agent 角色。
