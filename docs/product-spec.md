# 产品说明

## 目标

构建一个终端优先的交互式 AI 编程 Agent。它启动时绑定到单一目标 workspace，随后允许用户连续输入
自然语言任务；Agent 只能检查和修改该 workspace 内的文件，并在补丁应用前执行校验和用户确认。

## MVP 用户故事

- 作为开发者，我可以用 `code-agent --workspace <dir>` 启动一个绑定到单一 workspace 的交互会话。
- 作为开发者，我可以连续输入问题或修改请求，并得到结合 workspace 上下文的回复。
- 作为开发者，我可以通过 LLM Provider 为指定修改生成 unified diff。
- 作为开发者，我可以在 `git apply --check` 通过后手动确认是否应用补丁。
- 作为开发者，我可以确信目标 workspace 的 `.env` 不会影响 Agent 的模型配置或系统 prompt。

## 成功标准

- CLI 可以通过 `uv sync` 安装依赖后稳定运行。
- 未指定 `--workspace` 时返回用法错误。
- 旧入口 `ask`、`context`、`tool` 不再是有效命令。
- Agent 工作流由 LangGraph `StateGraph` 编排，节点和条件边清晰可测。
- `.env` 等敏感文件不会进入模型上下文，也不能被文件工具直接读取。
- 生成的补丁只有在 `git apply --check` 通过且用户确认后才会被应用。
- 每次运行都可以保存为本地 JSON 会话日志，便于审计和复盘。
