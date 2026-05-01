# Code Agent

Code Agent 是一个面向单一本地 workspace 的终端交互式 AI 编程助手。启动时必须指定目标
workspace，之后可以连续输入任务；每条任务都会开启独立 ReAct 会话，模型根据需要调用受控工具，
工具结果会作为 `<observation>` 加入历史并回传给模型，直到模型输出 `<final_answer>`。

当前 MVP 不使用 LangGraph。核心编排是普通 `while True` 循环，并实时记录 Agent 行为标签：
`<task>`、`<summary>`、`<action>`、`<observation>`、`<final_answer>`。

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

输入普通文本会触发一次独立 Agent 任务；输入 `/exit` 或 `/quit` 退出。空输入会被忽略。

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
- `--no-session`：不写入会话日志。

旧入口 `ask`、`context`、`tool` 已移除。

## ReAct 工具循环

每条用户任务底层执行如下循环：

```text
while True:
  call_provider(history)
  if response has <action>:
    execute tool
    append <observation>
    continue
  append <final_answer>
  break
```

模型每轮只能选择一个工具调用，工具调用格式为：

```text
<action>{"tool":"read_file","args":{"path":"README.md"}}</action>
```

当前仅提供这些工具：

- `read_file`
- `write_file`
- `edit_file`
- `list_files`
- `grep_search`
- `run_shell`

其中 `run_shell` 每次执行前都会在 CLI 中询问用户确认。文件写入工具会限制在 workspace 内，并拒绝触碰
敏感路径。

## 会话日志

默认每次任务会把完整行为历史保存到 Code-Agent 项目自身的 `.code-agent/sessions`，同时 CLI 实时打印
对应标签日志。每次 `code-agent>` 输入都是独立会话，不继承上一条任务的历史。

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
