# Code Agent

Code Agent 是一个面向本地代码仓库的终端优先 AI 编程助手。它会收集与任务相关的仓库上下文，
调用模型生成小范围修改建议，用 Git 校验补丁，按需应用补丁并运行测试，最后保存可审计的会话日志。

当前 MVP 使用 LangGraph `StateGraph` 编排 Agent 工作流，同时架构上预留了 Rich/Typer
交互界面、Embedding 检索、MCP 工具和多 Agent 协作等后续扩展空间。

## 快速开始

```bash
uv sync
uv run python -m code_agent --help
uv run python -m code_agent context "解释这个项目"
# 运行 ask 前先复制 .env.example 为 .env，并填入真实 API Key。
uv run python -m code_agent ask "总结这个仓库" --no-session
```

安装为 Python 包后，可以直接使用脚本入口：

```bash
code-agent ask "修复失败的测试"
```

## 大模型配置

`ask` 默认使用 `openai` provider，并自动读取仓库根目录下的 `.env`。当前 `.env.example`
已按阿里百炼 OpenAI 兼容接口配置：

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

模型名和 API Key 必须写在仓库 `.env` 中，Base URL 也会优先采用 `.env` 中的值；
`ask` 不再提供命令行模型覆盖参数。

配置好 `.env` 后，默认命令就会调用大模型生成回复和可能的补丁：

```bash
uv run python -m code_agent ask "为空名称添加校验"
```

如果希望在补丁校验通过后自动应用，并运行测试：

```bash
uv run python -m code_agent ask "修复失败的测试" --apply --test
```

如果只是做本地冒烟测试，不希望调用大模型，可以显式使用离线模式：

```bash
uv run python -m code_agent ask "总结这个仓库" --provider offline --no-session
```

## 命令

- `ask`：收集上下文、调用提供方、检测补丁，并可选地应用补丁和运行测试。
- `context`：打印将发送给模型的仓库上下文，便于调试召回结果。
- `tool list`：列出非敏感文件。
- `tool read`：读取单个非敏感文件。
- `tool search`：在非敏感文件中搜索文本。
- `tool run`：运行安全白名单内的 shell 命令。
- `tool detect-test`：打印自动识别出的测试命令。

## LangGraph 工作流

`ask` 命令底层由 LangGraph `StateGraph` 编排，当前图结构是固定的安全流程：

```text
collect_context -> call_provider -> extract_patch
    -> check_patch -> apply_patch -> run_tests -> finalize_run
```

其中 `check_patch`、`apply_patch`、`run_tests` 都由条件边控制：

- 没有传 `--apply` 时不会进入补丁校验和应用节点。
- 模型没有生成 diff 时不会修改工作区。
- 补丁必须先通过 `git apply --check`，才会进入真正应用节点。
- 只有补丁成功应用且传入 `--test` 时才会运行测试。

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

## 简历亮点方向

- 终端 AI 编程 Agent：使用 LangGraph 编排仓库上下文收集、模型调用、补丁生成和测试反馈闭环。
- 安全工具层：默认跳过敏感文件，限制 shell 命令，应用补丁前使用 `git apply --check` 校验。
- 可扩展架构：后续可以接入 Embedding 检索、Tree-sitter 符号索引、MCP 工具和多 Agent 协作。
