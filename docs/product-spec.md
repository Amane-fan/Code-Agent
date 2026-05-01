# 产品说明

## 目标

构建一个终端优先的交互式 AI 编程 Agent。它启动时绑定到单一目标 workspace，随后允许用户在同一个
终端窗口内连续输入自然语言任务；这些任务共享当前窗口记忆，Agent 只能通过受控工具检查和修改该
workspace。

## MVP 用户故事

- 作为开发者，我可以用 `code-agent --workspace <dir>` 启动一个绑定到单一 workspace 的交互会话。
- 作为开发者，我可以连续输入问题或修改请求，后续输入会继承当前窗口内的历史。
- 作为开发者，我可以看到 Agent 的 `<memory>`、`<task>`、`<summary>`、`<action>`、`<observation>`、`<final_answer>` 行为日志。
- 作为开发者，我可以在历史过长前使用 `/compact` 手动压缩上下文，也可以让 Agent 自动压缩旧轮次。
- 作为开发者，我可以用 `/memory` 查看当前压缩记忆，用 `/clear` 清空当前窗口记忆。
- 作为开发者，我可以让模型通过 `read_file`、`write_file`、`edit_file`、`list_files`、`grep_search` 检查或修改文件。
- 作为开发者，我可以在模型请求 `run_shell` 时手动确认是否执行命令。
- 作为开发者，我可以让 Code-Agent 在启动时加载内置 skill 元数据，并让模型通过 `load_skill` 按需加载完整 skill。
- 作为开发者，我可以确信目标 workspace 的 `.env` 不会影响 Agent 的模型配置或系统 prompt。

## 成功标准

- CLI 可以通过 `uv sync` 安装依赖后稳定运行。
- 未指定 `--workspace` 时返回用法错误。
- 旧入口 `ask`、`context`、`tool` 不再是有效命令。
- Agent 工作流不依赖 LangGraph，而是由普通 ReAct 循环编排。
- 每轮工具 observation 都会加入历史，并参与下一轮模型调用。
- 同一终端窗口内的下一条任务会收到上一条任务的历史或压缩后的 `<memory>`。
- 上下文压缩会保留最近轮次的完整事件，并把更旧轮次折叠为摘要。
- `.env` 等敏感文件不会进入模型上下文，也不能被文件工具直接读取或写入。
- `run_shell` 每次执行前都需要用户确认。
- 工具说明在启动时从工具注册表动态生成，系统 prompt 中不再硬编码具体工具清单。
- 启动上下文只包含 skill 元数据；完整 skill 正文只能通过 `load_skill` 工具 observation 进入后续上下文。
- 每个交互窗口可以保存为一份本地 JSON 会话日志，同一窗口内的多轮运行都写入该文件，便于审计和复盘。
