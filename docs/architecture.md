# 架构说明

## 组件

- CLI：用 Typer 解析顶层启动参数，用 prompt_toolkit 提供 `code-agent>` 输入循环，并用 Rich 渲染事件流。
- Conversation Session：保存当前终端窗口内的多轮历史、压缩摘要和近期完整轮次。
- LangGraph ReAct Runner：为每条用户输入执行一次工具循环，用 `StateGraph` 编排模型调用、工具执行、上限保护和最终回答。
- Provider 层：默认用 LangChain `ChatOpenAI` 包装 OpenAI-compatible chat model 调用，并保留确定性的离线模式。
- Prompt 构建：基础系统 prompt 来自 `src/code_agent/prompts/system.md`，工具说明和 skill 元数据在启动时动态拼接。
- Skill Registry：从 Code-Agent 自身 `skills/` 目录读取 `SKILL.md` 元数据，并由 `load_skill` 按需返回完整内容。
- 工具层：通过工具注册表统一提供工具执行和工具说明，默认包含文件、搜索、shell 和 `load_skill`。
- 会话存储：每个交互窗口创建一份 JSON 日志，并把同一窗口内的多轮运行追加到 `runs` 列表。

## 数据流

1. 用户运行 `code-agent --workspace /path/to/target-project`。
2. CLI 进入交互式循环，等待 `code-agent>` 输入。
3. `CodingAgent` 创建 Skill Registry 和工具注册表，并把动态工具说明、skill 元数据拼进 Provider instructions。
4. 用户输入普通文本后，CLI 从 Conversation Session 取出当前窗口记忆和未压缩近期轮次。
5. LangGraph Runner 在这些历史后追加新的 `<task>`，并把完整标签历史放入单次任务的 graph state。
6. Provider 返回 `<summary>` 加 `<action>` 或 `<final_answer>`。
7. 如果返回 `<action>`，Runner 通过 `execute_tool` 节点调用工具注册表，把结果作为 `<observation>` 追加到历史，然后回到 `call_model` 节点。
8. 如果模型调用 `load_skill`，完整 `SKILL.md` 会作为 observation 进入下一轮模型输入。
9. 如果返回 `<final_answer>`，Runner 到达 LangGraph `END`，把本轮运行写入当前窗口的同一份日志文件，并结束本次任务。
10. 如果窗口历史超过上限，Conversation Session 把旧轮次压缩为 `<memory>`，并保留最近完整轮次。
11. 如果模型连续调用工具超过 20 轮，Runner 进入 `limit` 节点，生成错误型 `<final_answer>` 并结束。

## 边界

- `--workspace` 是 Agent 唯一可观察和可修改的目标代码边界。
- 初始模型请求不自动包含文件内容；文件内容必须通过工具 observation 进入历史。
- 初始模型请求只包含 skill 元数据，不包含完整 skill 正文；完整正文只能通过 `load_skill` observation 进入历史。
- 会话记忆只在当前终端进程内存在，退出后不会自动恢复。
- 会话日志文件会保留同一窗口内的多轮运行；新建 `CodingAgent` 或重新启动 CLI 会创建新的日志文件。
- `<memory>` 是压缩后的对话摘要，只作为模型输入上下文；模型不应自行输出 `<memory>`。
- `.env`、私钥、`.git`、`.venv`、`node_modules` 等敏感路径不会被文件工具读取或写入。
- `run_shell` 以 workspace 为 `cwd`，每次执行前都需要用户确认。
- Code-Agent 项目自身提供运行配置、基础系统 prompt、工具注册表、skills 和会话日志。

## 扩展方向

- 为交互式 CLI 增加更多快捷键、命令帮助或可选 TUI 视图。
- 为大型 workspace 加入 Embedding 检索和符号索引。
- 在现有工具返回协议之上接入 MCP 风格的外部工具。
- 增加可恢复会话、长期偏好记忆或多 Agent 角色。
