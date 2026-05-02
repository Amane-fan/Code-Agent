# Code Agent

Code Agent 是一个终端优先的 AI 编程 Agent，用于在单一本地 workspace 内完成代码阅读、文件修改、
命令执行确认和多轮任务协作。项目以可审计、可控和可扩展为设计目标，通过 LangGraph 编排 ReAct
工具循环，并将所有文件与 shell 能力限制在用户显式指定的 workspace 边界内。

该项目适合用于构建本地代码助手、验证 Agent 工具协议、评估上下文记忆策略，或作为更完整工程化
AI 编程系统的基础实现。

## 核心能力

- **单 workspace 隔离**：启动时必须通过 `--workspace` 指定目标目录，文件工具和 shell 工具都以该目录为边界。
- **交互式任务循环**：在同一个 `code-agent>` 窗口内连续输入自然语言任务，后续任务会继承当前窗口记忆。
- **LangGraph ReAct 编排**：每条任务由 `StateGraph` 驱动模型调用、工具执行、结果回传和终止判断。
- **受控工具集**：内置文件读取、文件写入、文本替换、文件列表、文本搜索、shell 请求和 skill 加载工具。
- **人工确认 shell 命令**：模型请求执行 shell 命令时，CLI 会先展示命令并等待用户确认。
- **上下文压缩**：历史过长时可将较旧轮次压缩为 `<memory>`，同时保留近期完整事件。
- **会话审计日志**：默认将交互窗口内的多轮运行记录到本地 JSON 日志，便于排查和复盘。
- **按需加载 skills**：启动上下文只包含 skill 元数据，完整 `SKILL.md` 只能通过 `load_skill` 工具进入模型上下文。

## 运行要求

- Python `>=3.12`
- [uv](https://docs.astral.sh/uv/) 用于依赖安装和本地运行
- OpenAI-compatible chat model，或使用内置 `offline` provider 进行本地冒烟测试

## 快速开始

安装依赖：

```bash
uv sync
```

复制并配置环境变量：

```bash
cp .env.example .env
```

`.env` 示例：

```bash
API_KEY=替换为你的 API Key
BASE_URL=https://api.deepseek.com
MODEL=deepseek-v4-flash
```

启动交互式 Agent：

```bash
uv run python -m code_agent --workspace /path/to/target-project
```

安装为 Python 包后，也可以使用脚本入口：

```bash
code-agent --workspace /path/to/target-project
```

启动后会进入交互式输入：

```text
code-agent>
```

输入自然语言任务会触发一次 Agent 运行。输入 `/exit` 或 `/quit` 退出，空输入会被忽略。

## 本地离线测试

如果只需要验证 CLI、会话流程或工具协议，而不调用外部模型，可以使用 `offline` provider：

```bash
uv run python -m code_agent --workspace . --provider offline --no-session
```

`offline` provider 返回确定性结果，适合冒烟测试和自动化验证。

## 模型配置

默认 provider 为 `openai`，底层通过 LangChain `ChatOpenAI` 调用 OpenAI-compatible chat model。
配置只从 Code Agent 项目自身的 `.env` 或当前进程环境变量读取，不读取目标 workspace 的 `.env`，
避免目标项目影响 Agent 的系统行为。

推荐配置：

```bash
API_KEY=替换为你的 API Key
BASE_URL=https://api.deepseek.com
MODEL=deepseek-v4-flash
```

也可以使用 OpenAI 原生环境变量：

```bash
OPENAI_API_KEY=替换为你的 OpenAI API Key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
```

`BASE_URL` 可以填写 base URL；如果填写完整 `/chat/completions` endpoint，系统会自动剥离该后缀后传给
`ChatOpenAI`。

## CLI 参数

```bash
code-agent --workspace /path/to/project [--provider openai|offline] [--no-session]
```

- `--workspace`：必填。指定 Agent 可观察和可修改的目标 workspace。
- `--provider`：模型提供方。默认 `openai`，可选 `offline`。
- `--no-session`：不写入本地会话日志。

交互式命令：

- `/compact`：立即将较旧轮次压缩为当前窗口记忆。
- `/memory`：查看当前压缩摘要和保留的近期轮次数。
- `/clear`：清空当前窗口记忆。
- `/exit` 或 `/quit`：退出当前窗口。

## 工具循环

每条用户任务都会执行一次 ReAct 工具循环：

```text
START -> call_model
call_model -- action --> execute_tool -> call_model
call_model -- final_answer --> END
call_model/execute_tool -- max_iterations reached --> limit -> END
```

模型每轮最多选择一个工具调用，工具结果会以 `<observation>` 形式加入历史，并参与下一轮模型调用。
默认工具包括：

- `read_file`：读取 workspace 内的非敏感 UTF-8 文本文件。
- `write_file`：创建或覆盖 workspace 内的非敏感 UTF-8 文本文件。
- `edit_file`：对单个文件执行精确文本替换。
- `list_files`：列出 workspace 内的非敏感文件。
- `grep_search`：在 workspace 内执行大小写不敏感的文本搜索。
- `run_shell`：在 workspace 中请求执行 shell 命令，并要求用户确认。
- `load_skill`：按名称加载启动时已发现的完整 skill 指令。

## 架构概览

项目主要由以下模块组成：

- **CLI**：基于 Typer、prompt_toolkit 和 Rich 实现交互式终端体验。
- **Conversation Session**：维护当前窗口内的多轮历史、压缩摘要和近期完整轮次。
- **LangGraph ReAct Runner**：编排模型调用、工具执行、最大轮次保护和最终回答。
- **Provider 层**：封装 OpenAI-compatible chat model，并提供确定性的离线模式。
- **Prompt 构建**：加载基础系统 prompt，并动态拼接工具说明和 skill 元数据。
- **Tool Registry**：统一注册工具执行逻辑和工具说明。
- **Skill Registry**：从 Code Agent 自身受控目录读取 skill 元数据，并支持按需加载完整内容。
- **Session Logging**：将每个交互窗口的运行历史写入本地 JSON 日志。

更详细的设计说明见 [架构说明](docs/architecture.md)。

## 安全边界

Code Agent 默认采取保守的本地执行策略：

- 初始模型请求不自动包含 workspace 文件内容。
- 文件内容必须通过受控工具 observation 进入模型上下文。
- `.env`、私钥、凭据文件、`.git`、`.venv`、`node_modules` 等敏感路径不会被文件工具读取或写入。
- 疑似密钥的值会在工具输出展示或存储前脱敏。
- `run_shell` 每次执行前都需要用户确认。
- 目标 workspace 的 `.env`、prompt 文件和 `SKILL.md` 不会被当作 Code Agent 的系统配置加载。

完整说明见 [安全模型](docs/security.md)。

## MCP 示例

项目包含一个独立的 MCP 示例服务端和客户端，用于验证 MCP 工具暴露与调用流程：

终端 1 启动示例服务端：

```bash
uv run code-agent-mcp-server
```

终端 2 调用示例客户端：

```bash
uv run code-agent-mcp-client list-tools
uv run code-agent-mcp-client call code_agent_add --arguments '{"a":2,"b":3}'
```

示例服务默认监听 `127.0.0.1:8000`，通过 legacy SSE 暴露 `code_agent_echo`、
`code_agent_add` 和 `code_agent_word_count`。

## 项目文档

- [产品说明](docs/product-spec.md)
- [架构说明](docs/architecture.md)
- [工具协议](docs/tool-protocol.md)
- [安全模型](docs/security.md)
- [评测方案](docs/evaluation.md)

## 开发与测试

运行测试：

```bash
uv run pytest
```

运行标准库 unittest 发现：

```bash
uv run python -m unittest discover -s tests
```

安装开发依赖并执行静态检查：

```bash
uv sync --extra dev
uv run ruff check .
uv run mypy src
```

## 项目结构

```text
src/code_agent/
  agent.py          Agent 门面与运行入口
  cli.py            交互式 CLI
  context.py        上下文组装与压缩输入
  conversation.py   当前窗口记忆和历史管理
  providers.py      模型 provider 封装
  react.py          LangGraph ReAct 执行器
  session.py        会话日志写入
  skills.py         Skill 元数据发现与加载
  tools/            Tool 基类、自动注册和默认工具实现
docs/               产品、架构、安全、工具协议和评测文档
tests/              单元测试与集成测试
```
