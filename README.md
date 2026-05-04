# Terminal Code Agent

一个运行在终端中的代码代理，使用 Python、LangChain、LangGraph 和 uv 构建。启动时必须指定工作目录，agent 的文件工具只能访问该目录内部。

## 安装

先安装 uv，然后同步依赖：

```bash
uv sync
```

复制配置文件并填写模型凭据：

```bash
cp .env.example .env
```

`MODEL_NAME` 使用 LangChain `init_chat_model` 支持的 `provider:model` 格式，例如 `openai:gpt-4.1-mini`。API key 通过 `.env` 或环境变量提供，代码不会硬编码密钥。

## 运行

```bash
uv run terminal-code-agent --workdir .
```

也可以通过模块运行：

```bash
uv run python -m terminal_code_agent --workdir .
```

常用参数：

- `--workdir`：必填，agent 可访问的工作目录。
- `--thread-id`：会话 ID，默认 `default`。
- `--env-file`：配置文件路径，默认 `.env`。
- `--log-level`：覆盖配置中的日志级别。
- `--no-color`：禁用 Rich 彩色输出。

CLI 启动时会显示当前 workdir、thread 和日志文件路径；审批请求和最终回答会用结构化终端面板展示。交互输入显式启用 `readline`，用于改善 backspace、Ctrl-H 和 Delete 等按键在不同终端中的兼容性。

退出会话时输入 `exit` 或 `quit`。

## 示例

```text
user> 帮我查看项目结构
agent> [run] run_id=... workdir=/path/to/project
agent> [decision] budget ok: estimated=... budget=...
agent> [model] tool_calls=list_files
agent> [gate] allowed=['list_files']
agent> [tool] list_files success
agent> {"type":"final","answer":"..."}
```

## 工具

所有暴露给模型的工具都集中在 `src/terminal_code_agent/tools.py`，并使用 `@tool` 修饰：

- `list_files`：查看目录结构。
- `search_files`：按 glob 搜索文件名。
- `grep`：搜索文本或正则命中。
- `read_file`：读取文本文件，支持行号范围。
- `apply_patch`：使用 unified diff 修改文件。
- `write_file`：创建、覆盖或追加文件。
- `run_shell`：在工作目录下运行 shell 命令。
- `load_skill_resource`：读取 `skills/<skill_name>` 内资源。

## 人工审批

只读工具默认允许。`apply_patch`、`write_file`、`run_shell` 默认需要人工审批。终端会展示工具名、参数摘要和风险说明，然后等待：

- `y` / `yes`：批准。
- `n` / `no`：拒绝。
- `edit`：编辑工具参数后批准。

审批由 LangGraph `interrupt()` 暂停，并通过 `Command(resume=...)` 恢复，工具函数内部不会调用 `input()`。

## 安全限制

本项目不是完整安全沙箱。第一阶段安全策略用于降低误操作风险：

- 所有文件路径都会解析到 `--workdir` 内部，路径逃逸会被拒绝。
- `.env`、私钥、SSH key、云凭据、包管理凭据等敏感路径默认拒绝读取和写入。
- `run_shell` 固定在 `workdir` 中执行，并拒绝明显危险命令。
- 日志会脱敏并截断长文本。
- 工具失败会把错误类型、提示和关键 stdout/stderr 摘要反馈给后续修复步骤。

如果处理不可信仓库，建议在容器、虚拟机或受限用户下运行。

## 日志

日志默认写入 `.agent/logs/agent-YYYYMMDD-HHMMSS-ffffff-<session>.jsonl`，每次 CLI 会话生成一个独立文件。每行是一个 JSON 事件，包含 session、run、节点、工具、审批、观察和最终回答等审计信息。

## 测试

```bash
uv run pytest
uv run ruff check .
```

测试不依赖真实外部 LLM，模型相关流程使用 mock 或直接验证节点和路由。

## 常见问题

**最终回答为什么是纯文本？**

当前最终输出契约只保留面向用户的回答文本，CLI 会直接打印 `final_answer`。

**为什么写文件和运行命令都要审批？**

这些操作会修改真实工作目录或在本机执行命令，默认需要用户明确确认。

**能读取 `.env` 吗？**

不能。敏感路径默认拒绝，日志也不会记录密钥内容。
