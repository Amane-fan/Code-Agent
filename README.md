# Code Agent

Code Agent 是一个面向单一本地 workspace 的终端交互式 AI 编程助手。启动时必须指定目标
workspace，之后可以连续输入任务；每轮都会收集该 workspace 内的非敏感上下文，调用模型生成回复，
检测可能的 unified diff，并在补丁校验通过后询问是否应用。

当前 MVP 使用 LangGraph `StateGraph` 编排 Agent 工作流，同时保留受限工具层、补丁校验和会话日志。

## 快速开始

```bash
uv sync
uv run python -m code_agent --workspace /path/to/target-project
```

安装为 Python 包后，可以直接使用脚本入口：

```bash
code-agent --workspace /path/to/target-project
```

启动后会进入交互式输入：

```text
code-agent>
```

输入普通文本会触发一轮 Agent 任务；输入 `/exit` 或 `/quit` 退出。空输入会被忽略。

## 大模型配置

默认使用 `openai` provider。模型配置只从 Code-Agent 项目自身的 `.env` 或当前进程环境变量读取，
不会读取目标 workspace 的 `.env`，避免目标项目影响 Agent 系统行为。

`.env.example` 已按阿里百炼 OpenAI 兼容接口配置：

```bash
DASHSCOPE_API_KEY=替换为你的阿里百炼API_KEY
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/api/v2/apps/protocols/compatible-mode/v1
DASHSCOPE_MODEL=qwen3.6-plus
```

也可以使用 OpenAI 原生变量：

```bash
OPENAI_API_KEY=替换为你的 OpenAI API Key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
```

如果只是做本地冒烟测试，不希望调用大模型，可以显式使用离线模式：

```bash
uv run python -m code_agent --workspace . --provider offline --no-session
```

## 命令参数

CLI 只保留顶层交互式启动参数：

- `--workspace`：必填，指定 Agent 可观察和可修改的目标 workspace。
- `--provider`：模型提供方，默认 `openai`，可选 `offline`。
- `--max-files`：每轮最多发送给模型的上下文文件数。
- `--no-session`：不写入会话日志。
- `--unsafe`：保留为会话级选项，用于允许 workspace 内未来的高风险测试命令。

旧入口 `ask`、`context`、`tool` 已移除。

## 交互式补丁处理

如果模型回复中包含 diff，CLI 会自动执行以下流程：

```text
git apply --check
Apply patch? [y/N]
```

只有校验通过且用户输入 `y` 或 `yes` 时，补丁才会应用到目标 workspace。校验失败时只打印错误，
不会修改文件。

## LangGraph 工作流

每轮用户输入底层由 LangGraph `StateGraph` 编排：

```text
collect_context -> call_provider -> extract_patch -> finalize_run
```

交互式 CLI 在图执行结束后处理补丁校验和用户确认。所有上下文收集、补丁校验、补丁应用和测试命令
检测都绑定到 `--workspace` 指定的目录。

## 项目文档

- [产品说明](docs/product-spec.md)
- [架构说明](docs/architecture.md)
- [工具协议](docs/tool-protocol.md)
- [安全模型](docs/security.md)
- [评测方案](docs/evaluation.md)

## 开发

```bash
uv run python -m unittest discover -s tests
```

建议安装的可选开发工具：

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy src
```
