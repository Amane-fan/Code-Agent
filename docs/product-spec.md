# 产品说明

## 目标

构建一个终端优先的交互式 AI 编程 Agent。它启动时绑定到单一目标 workspace，随后允许用户连续输入
自然语言任务；每条任务都是独立 ReAct 会话，Agent 只能通过受控工具检查和修改该 workspace。

## MVP 用户故事

- 作为开发者，我可以用 `code-agent --workspace <dir>` 启动一个绑定到单一 workspace 的交互会话。
- 作为开发者，我可以连续输入问题或修改请求，每条输入都有独立上下文。
- 作为开发者，我可以看到 Agent 的 `<task>`、`<think>`、`<action>`、`<observation>`、`<final_answer>` 行为日志。
- 作为开发者，我可以让模型通过 `read_file`、`write_file`、`edit_file`、`list_files`、`grep_search` 检查或修改文件。
- 作为开发者，我可以在模型请求 `run_shell` 时手动确认是否执行命令。
- 作为开发者，我可以确信目标 workspace 的 `.env` 不会影响 Agent 的模型配置或系统 prompt。

## 成功标准

- CLI 可以通过 `uv sync` 安装依赖后稳定运行。
- 未指定 `--workspace` 时返回用法错误。
- 旧入口 `ask`、`context`、`tool` 不再是有效命令。
- Agent 工作流不依赖 LangGraph，而是由普通 ReAct 循环编排。
- 每轮工具 observation 都会加入历史，并参与下一轮模型调用。
- `.env` 等敏感文件不会进入模型上下文，也不能被文件工具直接读取或写入。
- `run_shell` 每次执行前都需要用户确认。
- 每次运行都可以保存为本地 JSON 会话日志，便于审计和复盘。
