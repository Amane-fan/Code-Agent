# Terminal Code Agent 开发文档

> 项目类型：终端 code agent  
> 技术栈：Python + LangChain + LangGraph + uv  
> 目标读者：Codex、代码 agent、项目开发者、代码审查者  
> 文档定位：本文件是实现说明，不是用户使用手册。用户使用手册另见 `README.md`。

---

## 1. 项目目标

本项目实现一个运行在终端中的代码代理。用户启动程序时指定一个工作目录，之后在同一个终端会话中进行多轮对话。每轮用户输入都会触发一次 LangGraph agent run；agent 以 ReAct 风格进行规划、工具调用、观察、修复和最终回答。

核心目标如下：

1. 使用 **LangGraph 显式图** 编排 agent，不使用黑盒 `create_react_agent` 替代自定义图。
2. 使用 **LangChain 原生模型、提示词、工具调用能力**。
3. 除“记忆管理”外，其余尽量使用 LangChain / LangGraph 原生机制。
4. 支持多轮对话，同一终端会话复用同一个 `thread_id`。
5. 启动时必须指定 agent 工作目录，所有文件工具只能访问该目录内部。
6. 工具全部使用 `@tool` 修饰，并集中在 `tools.py`。
7. 工具需要有清晰的中文描述、参数信息、返回值信息。
8. 系统提示词必须使用提示词模板，集中放在 `prompts.py`。
9. 上下文存储在 LangGraph state 中；每条对话消息至少包含 `role` 和 `content`。
10. 最终回答必须是合法 JSON。
11. 记录 agent 行为日志。
12. 终端中实时输出 agent 决策信息，例如 skill 选择、预算判断、工具调用、审批、观察和下一步摘要。
13. 模型配置从 `.env` 读取。
14. 项目使用 **uv** 管理依赖、虚拟环境、锁文件、运行和测试。
15. 代码需要适量中文注释，重点解释图路由、安全策略、上下文压缩、人工审批和工具错误处理。

---

## 2. 设计边界与默认假设

以下默认假设用于消除实现歧义。

1. **记忆管理**：不实现向量库、长期记忆、用户画像或跨会话检索。多轮对话依赖 LangGraph checkpointer、`thread_id`、`messages` 和 `context_summary`。
2. **持久化**：第一阶段默认使用进程内 checkpointer；可选支持 SQLite checkpointer。
3. **工作目录边界**：所有文件系统工具必须限制在启动时指定的 `workdir` 内部。
4. **工具风险等级**：只读工具默认允许；写文件、应用 patch、运行 shell 命令默认需要人工审批。
5. **敏感信息**：`.env`、私钥、token、云凭据、SSH key、包管理凭据等默认拒绝读取、写入和日志输出。
6. **模型输出**：最终输出是面向用户的纯文本；工具调用使用模型原生 `tool_calls`，但在 state 和日志中要保存结构化记录。
7. **错误修复**：工具可恢复错误进入 `observe` 写入上下文，再回到模型重新规划；最终文本不再做 schema 修复。
8. **上下文预算**：超过 token budget 时进入 `compact_context`，压缩历史后重新打包。
9. **终端交互**：第一阶段实现同步 CLI；streaming token 输出不是必须项，但可以使用 LangGraph 更新流展示节点决策。
10. **工具返回值**：所有工具返回 JSON 字符串，便于作为 `ToolMessage` 传回模型，也便于日志记录。

---

## 3. uv 项目管理规范

### 3.1 初始化项目

新建项目时建议使用：

```bash
uv init --package terminal-code-agent
cd terminal-code-agent
uv python pin 3.11
```

如果是在现有仓库中开发：

```bash
uv init --package
uv python pin 3.11
```

`uv` 管理项目时，依赖声明位于 `pyproject.toml`，锁定结果位于 `uv.lock`。`uv.lock` 应提交到版本控制；`.venv/` 不应提交。

### 3.2 推荐依赖

基础依赖：

```bash
uv add langchain langgraph langchain-openai pydantic pydantic-settings python-dotenv tiktoken rich
```

可选依赖：

```bash
uv add langgraph-checkpoint-sqlite
```

开发依赖：

```bash
uv add --dev pytest pytest-mock ruff mypy
```

如果需要 Anthropic、Google、OpenRouter 等 provider，可按实际 provider 增加：

```bash
uv add langchain-anthropic
uv add langchain-google-genai
uv add langchain-openrouter
```

### 3.3 `pyproject.toml` 示例

```toml
[project]
name = "terminal-code-agent"
version = "0.1.0"
description = "A terminal code agent built with LangChain and LangGraph."
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "langchain",
    "langgraph",
    "langchain-openai",
    "pydantic>=2",
    "pydantic-settings>=2",
    "python-dotenv",
    "tiktoken",
    "rich",
]

[project.optional-dependencies]
sqlite = ["langgraph-checkpoint-sqlite"]

[project.scripts]
terminal-code-agent = "terminal_code_agent.cli:main"

[dependency-groups]
dev = [
    "pytest",
    "pytest-mock",
    "ruff",
    "mypy",
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.11"
warn_unused_configs = true
disallow_untyped_defs = false
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

### 3.4 常用 uv 命令

```bash
# 安装 / 同步依赖
uv sync

# 运行终端 agent
uv run terminal-code-agent --workdir .

# 或通过模块运行
uv run python -m terminal_code_agent --workdir .

# 运行测试
uv run pytest

# 代码检查
uv run ruff check .
uv run mypy src

# 查看依赖树
uv tree

# 锁文件检查，CI 中建议使用
uv lock --check
uv run --locked pytest
```

---

## 4. 推荐目录结构

```text
.
├── AGENTS.md
├── README.md
├── pyproject.toml
├── uv.lock
├── .python-version
├── .env.example
├── .gitignore
├── skills/
│   └── python_project/
│       ├── SKILL.md
│       └── references/
│           └── code_agent_notes.md
├── src/
│   └── terminal_code_agent/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── graph.py
│       ├── llm.py
│       ├── logging_utils.py
│       ├── prompts.py
│       ├── schemas.py
│       ├── state.py
│       ├── token_budget.py
│       ├── tool_gate.py
│       ├── tool_runtime.py
│       └── tools.py
└── tests/
    ├── test_graph_routes.py
    ├── test_tools_path_safety.py
    ├── test_output_schema.py
    ├── test_token_budget.py
    ├── test_tool_gate.py
    └── test_cli_approval.py
```

模块职责：

| 模块               | 职责                                                         |
| ------------------ | ------------------------------------------------------------ |
| `cli.py`           | 解析参数、启动会话、驱动 LangGraph、处理人工审批、输出终端事件。 |
| `__main__.py`      | 支持 `python -m terminal_code_agent`。                       |
| `config.py`        | 读取 `.env` 和环境变量，提供 `Settings`。                    |
| `llm.py`           | 初始化 chat model，绑定模型参数。                            |
| `graph.py`         | 构建 LangGraph，定义节点函数和路由函数。                     |
| `state.py`         | 定义 `AgentState`、消息记录和 reducer。                      |
| `schemas.py`       | 定义 Pydantic schema，包括工具参数、工具结果、最终回答、决策对象。 |
| `prompts.py`       | 集中定义所有提示词模板。                                     |
| `tools.py`         | 集中放置所有 `@tool` 工具。                                  |
| `tool_runtime.py`  | 路径解析、安全检查、截断、JSON 序列化、shell 执行辅助函数。  |
| `tool_gate.py`     | 工具风险分级、审批策略、拒绝原因生成。                       |
| `token_budget.py`  | token 估算、预算计算、截断策略。                             |
| `logging_utils.py` | JSON Lines 日志、脱敏、长文本截断。                          |

约束：`tools.py` 必须包含所有暴露给模型的工具函数；辅助函数可以放在 `tool_runtime.py`，但不要把工具函数分散到多个文件。

---

## 5. 配置设计

### 5.1 `.env.example`

```dotenv
# 模型配置。使用 ChatOpenAI，MODEL_NAME 填裸模型名。
MODEL_NAME=gpt-4.1-mini
MODEL_TEMPERATURE=0
MODEL_MAX_TOKENS=4096
MODEL_TIMEOUT_SECONDS=120
MODEL_CONTEXT_WINDOW=128000

# OpenAI 或兼容 OpenAI API 服务的 Key。
OPENAI_API_KEY=

# 兼容 OpenAI API 的服务可使用 base_url。
MODEL_BASE_URL=

# Agent 行为配置。
TOKEN_BUDGET_RATIO=0.85
MAX_REPAIR_ATTEMPTS=2
MAX_TOOL_REPAIR_ATTEMPTS=1
MAX_COMPACT_ATTEMPTS=2
MAX_CONTEXT_CHARS_PER_TOOL_RESULT=12000
SHELL_TIMEOUT_SECONDS=60
REQUIRE_APPROVAL_FOR_WRITE=true
LOG_LEVEL=INFO
LOG_DIR=.agent/logs
SKILLS_DIR=skills
CHECKPOINT_DB=.agent/checkpoints.sqlite
```

### 5.2 `Settings` 设计

建议在 `config.py` 中使用 `pydantic-settings`：

```python
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置，统一从 .env 和环境变量读取。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    model_name: str = "gpt-4.1-mini"
    model_temperature: float = 0
    model_max_tokens: int = 4096
    model_timeout_seconds: int = 120
    model_context_window: int = 128000
    model_base_url: str | None = None

    token_budget_ratio: float = 0.85
    max_compact_attempts: int = 2
    max_context_chars_per_tool_result: int = 12000
    shell_timeout_seconds: int = 60
    require_approval_for_write: bool = True

    log_level: str = "INFO"
    log_dir: Path = Path(".agent/logs")
    skills_dir: Path = Path("skills")
    checkpoint_db: Path = Path(".agent/checkpoints.sqlite")
```

注意事项：

1. 不要在代码中硬编码 API key。
2. 不要在日志中输出 `.env` 完整内容。
3. 兼容 OpenAI API 的服务通过 `MODEL_BASE_URL` 接入，`MODEL_NAME` 填服务端模型名。
4. CLI 启动时可以支持 `--env-file`，但第一阶段不是必须。

---

## 6. 核心运行流程

### 6.1 用户视角流程

```text
用户启动：
uv run terminal-code-agent --workdir /path/to/project --thread-id default

终端进入循环：
user> 帮我查看项目结构
agent> [run] run_id=... workdir=/path/to/project
agent> [decision] selected_skills=["python_project"] reason="..."
agent> [decision] budget ok: estimated=1234 budget=90000
agent> [model] wants tool call: list_files {"path":".","max_depth":2}
agent> [gate] allowed: list_files
agent> [tool] list_files success entries=42
agent> [observe] found 42 entries under .
agent> {"type":"final", "answer":"...", ...}
```

修改类任务：

```text
user> 请帮我修改 README
agent> [model] wants tool call: write_file {...}
agent> [gate] needs approval: write_file will modify README.md
agent> 是否批准？y/n/edit > y
agent> [tool] write_file success path=README.md bytes=1234
agent> {"type":"final", "answer":"已修改 README.md", ...}
```

### 6.2 单轮 LangGraph 运行流程

每轮用户输入触发一次 graph invocation。输入 state 至少包含：

```json
{
  "thread_id": "default",
  "workdir": "/abs/path/to/project",
  "user_input": "用户本轮问题"
}
```

同一个 CLI 会话应使用相同 `thread_id`，使 checkpointer 能保存和恢复会话状态。

---

## 7. LangGraph 图结构

必须显式实现以下图，不得使用黑盒 agent 替代：

```text
START
  -> init_state
  -> skill_select
  -> context_pack
  -> budget_check

budget_check -- ok --> call_model
budget_check -- over_limit --> compact_context -> context_pack

call_model -- tool_calls --> tool_gate
call_model -- final --> final_answer -> END
tool_gate -- allowed --> tool_execute
tool_gate -- needs_approval --> human_approval
tool_gate -- denied --> call_model

human_approval -- approved --> tool_execute
human_approval -- rejected --> call_model

tool_execute -- success --> observe -> context_pack
tool_execute -- retryable_error --> observe -> context_pack
tool_execute -- fatal_error --> final_answer -> END
```

### 7.1 图构建骨架

```python
from langgraph.graph import END, START, StateGraph

from terminal_code_agent.state import AgentState


def build_graph(checkpointer):
    builder = StateGraph(AgentState)

    builder.add_node("init_state", init_state)
    builder.add_node("skill_select", skill_select)
    builder.add_node("context_pack", context_pack)
    builder.add_node("budget_check", budget_check)
    builder.add_node("compact_context", compact_context)
    builder.add_node("call_model", call_model)
    builder.add_node("tool_gate", tool_gate)
    builder.add_node("human_approval", human_approval)
    builder.add_node("tool_execute", tool_execute)
    builder.add_node("observe", observe)
    builder.add_node("final_answer", final_answer)

    builder.add_edge(START, "init_state")
    builder.add_edge("init_state", "skill_select")
    builder.add_edge("skill_select", "context_pack")
    builder.add_edge("context_pack", "budget_check")

    builder.add_conditional_edges(
        "budget_check",
        route_budget_check,
        {"ok": "call_model", "over_limit": "compact_context"},
    )
    builder.add_edge("compact_context", "context_pack")

    builder.add_conditional_edges(
        "call_model",
        route_model_result,
        {
            "tool_calls": "tool_gate",
            "final": "final_answer",
        },
    )

    builder.add_conditional_edges(
        "tool_gate",
        route_tool_gate,
        {
            "allowed": "tool_execute",
            "needs_approval": "human_approval",
            "denied": "call_model",
        },
    )

    builder.add_conditional_edges(
        "human_approval",
        route_human_approval,
        {"approved": "tool_execute", "rejected": "call_model"},
    )

    builder.add_conditional_edges(
        "tool_execute",
        route_tool_execute,
        {
            "success": "observe",
            "retryable_error": "observe",
            "fatal_error": "final_answer",
        },
    )
    builder.add_edge("observe", "context_pack")
    builder.add_edge("final_answer", END)

    return builder.compile(checkpointer=checkpointer)
```

### 7.2 路由字段约定

路由函数不要重新计算复杂逻辑，应只读取节点写入的 state 字段：

| 路由函数               | 读取字段              | 返回值                                        |
| ---------------------- | --------------------- | --------------------------------------------- |
| `route_budget_check`   | `budget_status`       | `ok` / `over_limit`                           |
| `route_model_result`   | `model_route`         | `tool_calls` / `final`                        |
| `route_tool_gate`      | `tool_gate_route`     | `allowed` / `needs_approval` / `denied`       |
| `route_human_approval` | `approval_result`     | `approved` / `rejected`                       |
| `route_tool_execute`   | `tool_execute_status` | `success` / `retryable_error` / `fatal_error` |

建议在 `AgentState` 中补充 `tool_gate_route` 字段，避免路由函数根据多个列表推断。

---

## 8. State 设计

### 8.1 `AgentState`

建议使用 `TypedDict`。对需要追加的 list 字段使用 reducer。

```python
import operator
from typing import Any, Literal, Optional
from typing_extensions import Annotated, TypedDict


class ChatRecord(TypedDict, total=False):
    role: Literal["system", "user", "assistant", "tool", "developer"]
    content: str
    name: Optional[str]
    tool_call_id: Optional[str]
    metadata: dict[str, Any]


class AgentState(TypedDict, total=False):
    run_id: str
    thread_id: str
    workdir: str
    user_input: str

    # 多轮对话和上下文材料。
    messages: Annotated[list[ChatRecord], operator.add]
    context_messages: list[dict[str, Any]]
    context_summary: str
    packed_context: str
    selected_skills: list[str]
    skill_context: str

    # token budget。
    estimated_tokens: int
    token_budget: int
    budget_status: Literal["ok", "over_limit"]
    compact_attempts: int

    # 模型结果状态。
    llm_calls: int
    model_response: dict[str, Any]
    model_route: Literal["tool_calls", "final"]
    force_final: bool

    # 工具调用、审批、观察。
    pending_tool_calls: list[dict[str, Any]]
    approved_tool_calls: list[dict[str, Any]]
    denied_tool_calls: list[dict[str, Any]]
    tool_gate_route: Literal["allowed", "needs_approval", "denied"]
    approval_request: dict[str, Any]
    approval_result: Literal["approved", "rejected", "none"]
    tool_results: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    tool_error: dict[str, Any]
    tool_execute_status: Literal["success", "retryable_error", "fatal_error"]

    # 审计信息。
    changed_files: list[str]
    commands_run: list[str]

    # 最终输出。
    final_answer: str
```

### 8.2 State 更新规则

1. 节点函数只返回增量更新，不直接修改传入 state。

2. `messages` 中每条记录必须至少包含：

   ```json
   {"role": "user", "content": "..."}
   ```

3. 工具结果进入 `messages` 时，必须包含 `role="tool"` 和 `tool_call_id`。

4. 大字段要截断后再写日志；state 中可以保存较完整结果，但仍要避免敏感内容。

5. 不要用全局变量保存会话消息、工作目录、审批状态或工具结果。

---

## 9. Pydantic Schema 设计

### 9.1 最终回答

最终模型输出是面向用户的纯文本，不再要求结构化 JSON schema。图状态使用
`final_answer: str` 保存该文本，CLI 直接打印此字段。

示例：

```text
已查看项目结构，主要代码位于 src/terminal_code_agent。
```

### 9.2 工具结果 schema

```python
class ToolResult(BaseModel):
    ok: bool
    tool: str
    data: dict = Field(default_factory=dict)
    error_type: Literal["retryable_error", "fatal_error"] | None = None
    message: str = ""
    hint: str = ""
    metadata: dict = Field(default_factory=dict)
```

成功格式：

```json
{
  "ok": true,
  "tool": "read_file",
  "data": {
    "path": "src/app.py",
    "content": "1: ..."
  },
  "metadata": {
    "truncated": false
  }
}
```

失败格式：

```json
{
  "ok": false,
  "tool": "read_file",
  "error_type": "retryable_error",
  "message": "文件不存在: src/missing.py",
  "hint": "请先使用 search_files 或 list_files 确认路径。",
  "metadata": {}
}
```

### 9.3 工具调用 schema

模型原生 tool call 在 state 中统一转换为：

```python
class PendingToolCall(BaseModel):
    id: str
    name: str
    args: dict
    raw: dict = Field(default_factory=dict)
```

### 9.4 Skill 选择 schema

```python
class SkillSelection(BaseModel):
    selected_skills: list[str] = Field(default_factory=list)
    reason: str = ""
```

### 9.5 Human approval schema

```python
class ApprovalRequest(BaseModel):
    type: Literal["tool_approval"] = "tool_approval"
    question: str
    tool_calls: list[PendingToolCall]
    risk: str


class ApprovalResume(BaseModel):
    decision: Literal["approved", "rejected"]
    edited_tool_calls: list[PendingToolCall] | None = None
    comment: str = ""
```

---

## 10. LLM 初始化

### 10.1 `llm.py`

```python
from langchain_openai import ChatOpenAI

from terminal_code_agent.config import Settings


def _normalize_openai_model_name(model_name: str) -> str:
    if model_name.startswith("openai:"):
        return model_name.split(":", 1)[1]
    if ":" in model_name:
        raise ValueError("MODEL_NAME 使用 ChatOpenAI 初始化，请配置为裸模型名。")
    return model_name


def build_chat_model(settings: Settings):
    """根据 .env 配置初始化 ChatModel。"""
    kwargs = {
        "model": _normalize_openai_model_name(settings.model_name),
        "temperature": settings.model_temperature,
        "timeout": settings.model_timeout_seconds,
        "max_tokens": settings.model_max_tokens,
    }
    if settings.model_base_url:
        kwargs["base_url"] = settings.model_base_url
    return ChatOpenAI(**kwargs)
```

约束：

1. 不要在节点中散落 provider SDK 初始化逻辑。
2. 不要硬编码模型名。
3. 不要在日志中记录 API key。
4. 工具调用使用 `model.bind_tools(TOOLS)` 或等价 LangChain 原生能力。
5. 可以在启动时构造一次 model，通过 graph runtime 或闭包传入节点，避免每次节点重新初始化。
6. DeepSeek thinking 模式的工具调用子轮必须回传 `reasoning_content`。
7. 新用户轮次开始时，应从历史上下文中清理旧的 `reasoning_content`。

---

## 11. 提示词模板设计

所有提示词集中在 `prompts.py`，至少包含：

1. `SKILL_SELECT_PROMPT`
2. `REACT_SYSTEM_PROMPT`
3. `COMPACT_CONTEXT_PROMPT`

### 11.1 ReAct 系统提示词

```python
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder


REACT_SYSTEM_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        """
你是一个终端 code agent，正在协助用户处理工作目录中的代码项目。

工作目录：{workdir}

必须遵守：
1. 优先理解任务和已有代码，再修改文件。
2. 文件访问只能使用提供的工具。
3. 修改文件前，先读取相关文件或确认目标路径。
4. 对高风险操作会进入人工审批。
5. 如需调用工具，使用模型原生 tool calls。
6. 如不需要工具并准备结束，直接输出面向用户的最终回答文本。
7. 不要输出 Markdown 代码块包裹最终回答，不要输出 JSON 结构。
8. 不要泄露密钥、token、私钥或 `.env` 内容。
9. 不要虚构文件内容、命令结果或工具观察。
10. 如果上一次工具调用失败，请根据工具观察和错误信息重新规划；不要自动重复同一个错误调用。

当前已选择的 skills：
{selected_skills}

skill 上下文：
{skill_context}

压缩后的历史摘要：
{context_summary}

最近观察：
{observations}

上次工具错误或修复建议：
{tool_error}

可用工具：
{tool_names}
""",
    ),
    MessagesPlaceholder("messages"),
])
```

### 11.2 Skill 选择提示词

输出必须是 JSON：

```json
{
  "selected_skills": ["python_project"],
  "reason": "用户要求实现 Python LangGraph 项目"
}
```

要求：

1. 只能从扫描到的 skill 名称中选择。
2. 只根据 frontmatter `description` 判断是否需要加载。
3. 没有合适 skill 时输出空数组。
4. 不要选择过多 skill，优先 0 到 3 个。
5. 输出不得包含 Markdown。

### 11.3 上下文压缩提示词

压缩结果应保留：

1. 用户当前任务。
2. 用户明确约束。
3. 已选择 skill。
4. 已读取文件和关键事实。
5. 已修改文件。
6. 已执行命令。
7. 失败的工具调用、错误原因和修复建议。
8. 尚未解决的问题。

---

## 12. 工具设计

所有工具位于 `src/terminal_code_agent/tools.py`，使用 `@tool` 修饰，返回 JSON 字符串。工具参数用 Pydantic schema 描述。

### 12.1 工具清单

| 工具                  | 类型     | 默认策略              | 作用                           |
| --------------------- | -------- | --------------------- | ------------------------------ |
| `list_files`          | 只读     | allowed               | 查看目录结构。                 |
| `search_files`        | 只读     | allowed               | 按文件名 glob 搜索。           |
| `grep`                | 只读     | allowed               | 按文本或正则搜索文件内容。     |
| `read_file`           | 只读     | allowed，敏感文件除外 | 读取文件内容，支持行号范围。   |
| `apply_patch`         | 写入     | needs_approval        | 使用 unified diff 修改文件。   |
| `write_file`          | 写入     | needs_approval        | 创建、覆盖或追加文件。         |
| `run_shell`           | 执行命令 | needs_approval        | 在 workdir 下运行 shell 命令。 |
| `load_skill_resource` | 只读     | allowed               | 读取 skill 目录中的资源。      |

### 12.2 `@tool` 基本模式

```python
from langchain.tools import ToolRuntime, tool
from pydantic import BaseModel, Field


class ReadFileInput(BaseModel):
    path: str = Field(description="相对于工作目录的文件路径")
    start_line: int | None = Field(default=None, ge=1, description="起始行号，1-based")
    end_line: int | None = Field(default=None, ge=1, description="结束行号，包含该行")
    max_chars: int = Field(default=20000, ge=100, le=100000, description="最多返回字符数")


@tool(args_schema=ReadFileInput)
def read_file(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    max_chars: int = 20000,
    runtime: ToolRuntime | None = None,
) -> str:
    """读取工作目录中的文本文件。

    参数：
    - path：相对于工作目录的文件路径。
    - start_line：可选，起始行号，1-based。
    - end_line：可选，结束行号，包含该行。
    - max_chars：最多返回字符数。

    返回：
    - JSON 字符串。成功时包含带行号的文件内容；失败时包含 error_type、message 和 hint。
    """
    ...
```

工具实现中从 `runtime.state["workdir"]` 读取工作目录。测试时可提供辅助执行入口，避免依赖真实 LangGraph runtime。

### 12.3 `list_files`

参数：

```python
class ListFilesInput(BaseModel):
    path: str = Field(default=".", description="相对于工作目录的目录路径")
    max_depth: int = Field(default=2, ge=0, le=8, description="最大递归深度")
    include_hidden: bool = Field(default=False, description="是否包含隐藏文件")
    max_entries: int = Field(default=200, ge=1, le=1000, description="最多返回条目数")
```

返回数据：

```json
{
  "root": ".",
  "entries": [
    {"path": "src", "type": "dir"},
    {"path": "src/app.py", "type": "file", "size": 1234}
  ]
}
```

实现要求：

1. 默认忽略隐藏文件和常见大目录：`.git`、`.venv`、`node_modules`、`__pycache__`、`.mypy_cache`、`.pytest_cache`。
2. 返回相对路径。
3. 超过 `max_entries` 时截断，并设置 `metadata.truncated=true`。

### 12.4 `search_files`

参数：

```python
class SearchFilesInput(BaseModel):
    pattern: str = Field(description="文件名匹配模式，支持 glob，例如 '*.py' 或 '*agent*'")
    path: str = Field(default=".", description="相对于工作目录的搜索起点")
    include_hidden: bool = Field(default=False, description="是否包含隐藏文件")
    max_results: int = Field(default=100, ge=1, le=1000, description="最多返回结果数")
```

实现要求：

1. 使用 Python `Path.rglob` 或等价方式，不拼接 shell 命令。
2. 跳过忽略目录。
3. 仅返回 workdir 内路径。
4. 结果按路径排序，便于测试稳定。

### 12.5 `grep`

参数：

```python
class GrepInput(BaseModel):
    pattern: str = Field(description="要搜索的文本或正则表达式")
    path: str = Field(default=".", description="相对于工作目录的搜索起点")
    glob: str = Field(default="*", description="文件 glob 过滤，例如 '*.py'")
    case_sensitive: bool = Field(default=True, description="是否大小写敏感")
    regex: bool = Field(default=False, description="是否按正则表达式搜索")
    context_lines: int = Field(default=0, ge=0, le=5, description="返回命中前后的上下文行数")
    max_results: int = Field(default=100, ge=1, le=1000, description="最多返回命中数")
```

实现要求：

1. 不使用 shell `grep`，避免命令注入。
2. 跳过二进制文件。
3. 跳过过大文件，例如超过 2 MB 的文本文件，可在 metadata 中记录 skipped。
4. 返回命中路径、行号、行内容和上下文。
5. 正则无效时返回 `retryable_error`。

### 12.6 `read_file`

实现要求：

1. 支持 `start_line` / `end_line`。
2. 行号为 1-based。
3. 返回内容必须带行号，例如 `12: def main():`。
4. 对超长内容截断，并标记 `truncated=true`。
5. 拒绝读取敏感路径。
6. 二进制文件返回 `retryable_error`。

### 12.7 `apply_patch`

参数：

```python
class ApplyPatchInput(BaseModel):
    patch: str = Field(description="unified diff 格式的 patch 内容")
```

实现要求：

1. 默认需要审批。
2. patch 中的文件路径必须全部位于 workdir 内。
3. 禁止绝对路径和 `../`。
4. 优先执行 `git apply --check` 校验，再执行 `git apply`。
5. 捕获 stdout、stderr 和 exit code。
6. patch 冲突返回 `retryable_error`。
7. 安全策略拒绝返回 `fatal_error`。
8. 成功时返回修改文件列表。

### 12.8 `write_file`

参数：

```python
class WriteFileInput(BaseModel):
    path: str = Field(description="相对于工作目录的文件路径")
    content: str = Field(description="要写入的文件内容")
    mode: Literal["overwrite", "append", "create_only"] = Field(default="create_only")
    create_parents: bool = Field(default=True)
```

实现要求：

1. 默认需要审批。
2. `create_only` 模式下文件已存在应返回 `retryable_error`。
3. `overwrite` 会覆盖文件，审批信息中必须明确风险。
4. 写入后返回路径、模式、字节数。
5. 拒绝写入敏感路径。

### 12.9 `run_shell`

参数：

```python
class RunShellInput(BaseModel):
    command: str = Field(description="要执行的 shell 命令")
    timeout_seconds: int | None = Field(default=None, ge=1, le=600, description="超时时间")
```

实现要求：

1. 默认需要审批。
2. `cwd` 固定为 `workdir`。
3. 不允许模型传入 `cwd`。
4. 使用 `subprocess.run`，捕获 stdout、stderr、exit code。
5. 命令超时返回 `retryable_error`。
6. 明显危险命令返回 `fatal_error`。
7. 输出截断后写入 metadata。

第一阶段禁止或拒绝的命令模式至少包括：

```text
sudo
su
rm -rf /
rm -rf ~
:(){ :|:& };:
chmod -R 777 /
chown -R
cat ~/.ssh/*
cat .env
curl ... | sh
wget ... | sh
```

说明：此处是最低限度保护，不是完整沙箱。生产环境应使用容器、seccomp、只读挂载、网络限制和资源配额。

### 12.10 `load_skill_resource`

参数：

```python
class LoadSkillResourceInput(BaseModel):
    skill_name: str = Field(description="skill 名称，对应 skills/<skill_name>")
    resource_path: str = Field(default="SKILL.md", description="skill 内部资源相对路径")
    max_chars: int = Field(default=20000, ge=100, le=100000, description="最多返回字符数")
```

实现要求：

1. 只能读取 `SKILLS_DIR/<skill_name>` 内部资源。
2. 禁止路径逃逸。
3. 返回资源文本和元数据。
4. 若资源不存在，返回 `retryable_error`。

---

## 13. 路径安全与敏感信息策略

### 13.1 统一路径解析

`tool_runtime.py` 中实现：

```python
from pathlib import Path


class SecurityError(Exception):
    """安全策略拒绝。"""


def resolve_in_root(root: Path, user_path: str) -> Path:
    """把用户传入路径解析到 root 内部，禁止路径逃逸。"""
    base = root.resolve()
    target = (base / user_path).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise SecurityError(f"路径逃逸出允许目录: {user_path}") from exc
    return target
```

### 13.2 敏感路径匹配

至少拒绝：

```text
.env
.env.*
*.pem
*.key
id_rsa
id_dsa
id_ecdsa
id_ed25519
.ssh/*
.aws/credentials
.gcloud/*
.azure/*
.npmrc
.pypirc
.netrc
```

实现建议：

```python
SENSITIVE_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    ".ssh/*",
    ".aws/credentials",
    ".gcloud/*",
    ".azure/*",
    ".npmrc",
    ".pypirc",
    ".netrc",
]
```

匹配应基于 workdir 相对路径。发现敏感路径时：

1. 工具返回 `fatal_error`。
2. 日志只记录路径被拒绝，不记录内容。
3. 模型观察中只说明安全策略拒绝。

---

## 14. 工具审批策略

### 14.1 风险分级

| 风险级别 | 工具                                                         | 处理                       |
| -------- | ------------------------------------------------------------ | -------------------------- |
| 低       | `list_files`、`search_files`、`grep`、`read_file`、`load_skill_resource` | 默认允许。                 |
| 中       | `read_file` 读取大文件、二进制、疑似敏感路径                 | 大文件截断；敏感路径拒绝。 |
| 高       | `apply_patch`、`write_file`、`run_shell`                     | 默认需要人工审批。         |
| 禁止     | 路径逃逸、读取密钥、破坏性命令                               | 直接拒绝，不进入审批。     |

### 14.2 `tool_gate` 输出

`tool_gate` 读取 `pending_tool_calls`，输出：

```json
{
  "tool_gate_route": "needs_approval",
  "approval_request": {
    "type": "tool_approval",
    "question": "是否允许执行以下工具调用？",
    "tool_calls": [...],
    "risk": "将修改工作目录中的文件"
  }
}
```

未知工具：

```json
{
  "tool_gate_route": "denied",
  "denied_tool_calls": [
    {
      "name": "unknown_tool",
      "reason": "未知工具，不能执行"
    }
  ],
  "messages": [
    {
      "role": "tool",
      "content": "工具调用被拒绝：unknown_tool 不存在。请重新规划。"
    }
  ]
}
```

### 14.3 审批范围

当同一批 tool calls 中既有只读工具又有高风险工具时，推荐整批进入审批，避免模型利用批量调用绕过策略。审批通过后执行已批准的整批工具调用；审批拒绝后不执行任何工具调用。

---

## 15. Human-in-the-loop 设计

### 15.1 节点职责

`human_approval` 必须使用 LangGraph `interrupt()`，不要在节点内部直接 `input()`。

伪代码：

```python
from langgraph.types import interrupt


def human_approval(state: AgentState):
    request = state["approval_request"]
    resume_value = interrupt(request)
    # resume_value 由 CLI 通过 Command(resume=...) 传回。
    decision = parse_approval_resume(resume_value)
    if decision.decision == "approved":
        return {
            "approval_result": "approved",
            "approved_tool_calls": decision.edited_tool_calls or state["pending_tool_calls"],
        }
    return {
        "approval_result": "rejected",
        "messages": [
            {
                "role": "assistant",
                "content": "用户拒绝了工具调用。请基于拒绝结果重新规划。",
            }
        ],
    }
```

### 15.2 CLI 审批恢复

CLI 检测到 interrupt 后：

1. 展示工具名、参数摘要、风险说明。
2. 要求用户输入：
   - `y` / `yes`：批准。
   - `n` / `no`：拒绝。
   - `e` / `edit`：编辑工具参数后批准。
3. 使用相同 `thread_id` 调用 `Command(resume=...)` 恢复图执行。

伪代码：

```python
from langgraph.types import Command

config = {"configurable": {"thread_id": thread_id}}
result = graph.invoke(input_state, config=config)

if "__interrupt__" in result:
    payload = result["__interrupt__"][0].value
    resume_payload = ask_user_for_approval(payload)
    result = graph.invoke(Command(resume=resume_payload), config=config)
```

---

## 16. 节点实现细节

### 16.1 `init_state`

职责：初始化本轮 agent run。

输入：`thread_id`、`workdir`、`user_input`。

输出：

1. `run_id`。
2. 规范化后的 `workdir`。
3. 追加用户消息：`{"role":"user","content": user_input}`。
4. 重置本轮临时字段：`pending_tool_calls`、`approved_tool_calls`、`denied_tool_calls`、`tool_results`、`observations`、`approval_result`、`tool_error`。
5. 写日志 `run_start`。
6. 终端输出本轮开始和任务摘要。

注意：不要清空历史 `messages`。多轮历史由 checkpointer 管理；本节点只追加本轮用户输入。

### 16.2 `skill_select`

职责：根据本轮任务选择 skill。

实现步骤：

1. 扫描 `SKILLS_DIR`。
2. 读取每个 `skills/<dir>/SKILL.md` 的 YAML frontmatter，只使用 `name` 和 `description`。
3. 使用 `SKILL_SELECT_PROMPT` 调用 LLM，基于 `description` 判断是否需要加载 skill。
4. 解析 `SkillSelection` JSON。
5. 对选中的 skill 加载 `SKILL.md` 内容。
6. 写入 `selected_skills` 和 `skill_context`。
7. 记录日志并输出选择原因。

失败策略：

1. skills 目录不存在：选择空列表。
2. 某个 `SKILL.md` 缺少合法 frontmatter、`name` 或 `description`：跳过该 skill。
3. LLM 输出非法：选择空列表，并记录 `skill_select_parse_failed`。
4. 某个 skill 资源读取失败：跳过该 skill。

### 16.3 `context_pack`

职责：组装下一次模型调用所需上下文。

输入材料：

1. 最近 `messages`。
2. `context_summary`。
3. `selected_skills`。
4. `skill_context`。
5. 最近 `observations`。
6. `tool_error`。
7. 当前用户任务。

输出：

1. `context_messages`：供 `call_model` 使用的 LangChain message 列表或可转换 dict。
2. `packed_context`：用于估算 token 的文本表示。
3. `estimated_tokens` 初步值。

注意：这里不调用 LLM，只做组装和估算。

### 16.4 `budget_check`

职责：判断上下文是否超过预算。

预算公式：

```python
token_budget = int((MODEL_CONTEXT_WINDOW - MODEL_MAX_TOKENS) * TOKEN_BUDGET_RATIO)
```

判断：

```python
budget_status = "ok" if estimated_tokens <= token_budget else "over_limit"
```

token 估算：

1. 优先使用 `tiktoken`。
2. 不支持模型 tokenizer 时，使用 `len(text) // 4` 估算。
3. 对中文可更保守，例如 `max(len(text) // 2, len(text.encode("utf-8")) // 4)`。

输出终端事件：

```text
[decision] budget ok: estimated=1234 budget=90000
```

### 16.5 `compact_context`

职责：压缩上下文。

实现步骤：

1. 检查 `compact_attempts`。
2. 超过 `MAX_COMPACT_ATTEMPTS` 时，生成 fallback final 或强制提示模型尽快结束。
3. 使用 `COMPACT_CONTEXT_PROMPT` 压缩旧消息和旧观察。
4. 写入 `context_summary`。
5. 增加 `compact_attempts`。
6. 返回 `context_pack`。

必须保留：

1. 当前用户任务。
2. 用户明确约束。
3. 已读关键文件。
4. 已修改文件。
5. 已执行命令。
6. 工具结果中的关键事实。
7. 未解决错误。

### 16.6 `call_model`

职责：调用 LLM 决策下一步。

处理逻辑：

1. 如果 `force_final=true`，不调用 LLM，直接设置 `model_route="final"`。
2. 构造 `REACT_SYSTEM_PROMPT`。
3. 对模型执行 `bind_tools(TOOLS)`。
4. 调用模型。
5. 若响应包含 `tool_calls`：
   - 写入 `pending_tool_calls`。
   - 写入 `model_route="tool_calls"`。
   - 终端输出工具名和参数摘要。
6. 若响应无 `tool_calls`：
   - 直接把 `content` 写入 `final_answer`。
   - 写入 `model_route="final"`。
7. 增加 `llm_calls`。

注意：不要让模型在工具结果尚未写入 `messages` 的情况下假设工具已经执行。

### 16.7 `tool_gate`

职责：判断工具调用是否允许。

实现步骤：

1. 校验工具名是否存在。
2. 校验参数是否能被工具 schema 解析。
3. 对路径参数做安全预检。
4. 对敏感路径做拒绝。
5. 对风险等级做判断。
6. 写入 `approved_tool_calls`、`denied_tool_calls` 或 `approval_request`。
7. 设置 `tool_gate_route`。

路由策略：

1. 任意未知工具或安全拒绝：`denied`。
2. 任意高风险工具：`needs_approval`。
3. 全部只读且安全：`allowed`。

### 16.9 `human_approval`

职责：暂停图执行，等待用户审批。

要求：

1. 使用 `interrupt()`。
2. payload 必须 JSON 可序列化。
3. 恢复时解析 `Command(resume=...)` 的值。
4. 审批通过则写入 `approved_tool_calls`。
5. 审批拒绝则追加观察，让模型重新规划。

### 16.10 `tool_execute`

职责：执行已允许或已批准的工具调用。

执行策略：

1. 顺序执行工具调用。
2. 第一个 fatal error 出现时停止后续工具。
3. 第一个 retryable error 出现时停止后续工具，进入 `observe` 并把错误写入上下文。
4. 全部成功后进入 `observe`。
5. 将每个工具结果转换为 `ToolMessage` 并追加到 `messages`。

输出字段：

1. `tool_results`。
2. `tool_execute_status`。
3. `tool_error`。
4. `changed_files`。
5. `commands_run`。

### 16.11 `observe`

职责：把工具结果转换成结构化观察。

实现步骤：

1. 解析工具返回 JSON。
2. 提取摘要，例如：命中数量、文件路径、行号、修改文件、命令退出码。
3. 截断长文本。
4. 写入 `observations`。
5. 追加一条可读观察到 `messages`。
6. 输出终端摘要。

### 16.12 `final_answer`

职责：生成最终输出。

要求：

1. 输出 `final_answer`。
2. 若 `final_answer` 不存在，应根据当前 state 生成 fallback 文本。
3. 记录日志 `final_answer`。
4. CLI 直接打印最终文本。

---

## 17. CLI 设计

### 17.1 启动参数

```bash
uv run terminal-code-agent --workdir . --thread-id default
```

参数建议：

| 参数          | 默认值     | 说明                         |
| ------------- | ---------- | ---------------------------- |
| `--workdir`   | 必填       | agent 工作目录。             |
| `--thread-id` | `default`  | 会话 ID，用于 checkpointer。 |
| `--env-file`  | `.env`     | 可选，配置文件路径。         |
| `--log-level` | 从配置读取 | 覆盖日志级别。               |
| `--no-color`  | false      | 禁用彩色终端输出。           |

CLI 启动时展示 workdir、thread 和日志路径。用户输入和审批输入使用统一入口，并显式初始化
`readline`，绑定 backspace / Ctrl-H / Delete 等常见删除键，避免不同终端退格行为不一致。

### 17.2 对话循环

伪代码：

```python
def main():
    args = parse_args()
    settings = load_settings(args.env_file)
    graph = build_graph(checkpointer=build_checkpointer(settings))
    config = {"configurable": {"thread_id": args.thread_id}}

    while True:
        user_input = input("user> ").strip()
        if user_input.lower() in {"exit", "quit"}:
            break

        state_input = {
            "thread_id": args.thread_id,
            "workdir": str(resolve_workdir(args.workdir)),
            "user_input": user_input,
        }
        result = run_graph_with_approval_loop(graph, state_input, config)
        print_final(result)
```

### 17.3 终端事件输出

建议统一事件格式：

```text
[run] run_id=... workdir=...
[decision] selected_skills=[...] reason=...
[decision] budget ok: estimated=1234 budget=90000
[model] tool_calls=list_files, read_file
[gate] allowed=list_files
[gate] needs_approval=write_file risk="将修改 README.md"
[tool] list_files success entries=42
[observe] src contains 10 python files
[repair] invalid final JSON, retry=1/2
[final] done
```

不要把大段文件内容直接打印到终端决策流中；可以只打印摘要。

---

## 18. 日志设计

### 18.1 日志格式

使用 JSON Lines，每行一个事件：

```json
{
  "timestamp": "2026-05-04T12:00:00+08:00",
  "level": "INFO",
  "session_id": "...",
  "event": "tool_execute",
  "run_id": "...",
  "thread_id": "default",
  "node": "tool_execute",
  "message": "executed tool",
  "data": {
    "tool": "list_files",
    "ok": true
  }
}
```

日志默认写入 `.agent/logs/agent-YYYYMMDD-HHMMSS-ffffff-<session>.jsonl`，每次 CLI 会话生成一个独立文件。

### 18.2 必须记录的事件

1. `run_start`
2. `node_start`
3. `node_end`
4. `skill_select`
5. `context_pack`
6. `budget_check`
7. `compact_context`
8. `call_model`
9. `model_decision`
10. `tool_gate`
11. `human_approval`
12. `tool_execute`
13. `observe`
14. `final_answer`
15. `run_end`

### 18.3 脱敏与截断

日志写入前必须处理：

1. API key、token、私钥内容替换为 `[REDACTED]`。
2. `.env` 内容不记录。
3. 大字段按字符数截断，例如 4000 字符。
4. shell stdout / stderr 长输出截断。
5. patch 内容可记录摘要，不记录完整大 patch。

建议提供：

```python
def redact(value: object) -> object:
    """递归脱敏日志数据。"""
    ...


def truncate_text(text: str, max_chars: int = 4000) -> str:
    """截断长文本并附加标记。"""
    ...
```

---

## 19. Token budget 与上下文压缩

### 19.1 预算计算

```python
def compute_token_budget(context_window: int, max_tokens: int, ratio: float) -> int:
    return int((context_window - max_tokens) * ratio)
```

示例：

```text
MODEL_CONTEXT_WINDOW=128000
MODEL_MAX_TOKENS=4096
TOKEN_BUDGET_RATIO=0.85
TOKEN_BUDGET=int((128000 - 4096) * 0.85)=105318
```

### 19.2 token 估算

```python
def estimate_tokens(text: str, model_name: str | None = None) -> int:
    try:
        import tiktoken
        # 根据 model_name 选择 encoding；失败时 fallback。
        ...
    except Exception:
        return max(len(text) // 2, len(text.encode("utf-8")) // 4)
```

### 19.3 压缩策略

优先压缩：

1. 旧工具结果。
2. 旧对话消息。
3. 重复观察。
4. 长文件内容。

不得压缩丢失：

1. 当前用户任务。
2. 用户明确约束。
3. 已修改文件。
4. 已执行命令。
5. 未解决错误。
6. 审批拒绝记录。

### 19.4 防止压缩死循环

增加 `compact_attempts`。超过上限时：

1. 写入风险说明。
2. 设置 `force_final=true`。
3. 让 `call_model` 生成或直接路由最终 JSON。

---

## 20. Skill 机制

### 20.1 目录约定

```text
skills/
└── python_project/
    ├── SKILL.md
    └── references/
        └── code_agent_notes.md
```

### 20.2 `skill_select` 规则

1. 每轮用户任务都会进入 skill 选择。
2. 使用 LLM 从现有 skill 中选择，选择依据只来自 frontmatter 的 `description`。
3. 只能选择真实存在的 skill。
4. 没有合适 skill 时选择空列表。
5. 选择结果写入 `selected_skills`。
6. 选中后加载 `SKILL.md` 内容写入 `skill_context`。

### 20.3 `load_skill_resource` 规则

该工具允许模型后续按需读取 skill 资源，但只能读取 `SKILLS_DIR/<skill_name>` 内部文件。

路径校验：

```python
skill_root = (skills_dir / skill_name).resolve()
target = (skill_root / resource_path).resolve()
target.relative_to(skill_root)
```

### 20.4 Skill 上下文控制

不要一次性把所有 references 全量塞入上下文。建议：

1. `skill_select` 阶段只用 frontmatter `description` 做选择，选中后加载对应 `SKILL.md`。
2. 模型需要细节时调用 `load_skill_resource`。
3. 每个 skill 上下文最多，例如 8000 到 12000 字符。

---

## 21. 错误分类与恢复策略

### 21.1 模型输出

| 情况                    | 处理                              |
| ----------------------- | --------------------------------- |
| 无 tool calls           | 直接写入 `final_answer`           |
| 输出内容看起来像 JSON   | 仍作为普通文本写入 `final_answer` |
| 模型未返回内容          | `final_answer` 节点生成兜底文本   |

### 21.2 工具错误

| 错误             | 类型              | 处理                                     |
| ---------------- | ----------------- | ---------------------------------------- |
| 文件不存在       | `retryable_error` | `observe -> context_pack -> call_model`  |
| 参数 schema 错误 | `retryable_error` | `observe -> context_pack -> call_model`  |
| 正则表达式错误   | `retryable_error` | `observe -> context_pack -> call_model`  |
| patch 冲突       | `retryable_error` | `observe -> context_pack -> call_model`  |
| 命令超时         | `retryable_error` | `observe -> context_pack -> call_model`  |
| 路径逃逸         | `fatal_error`     | `final_answer` 或 `denied -> call_model` |
| 敏感路径访问     | `fatal_error`     | `final_answer` 或 `denied -> call_model` |
| 危险 shell 命令  | `fatal_error`     | `final_answer` 或 `denied -> call_model` |

### 21.3 `tool_gate` 拒绝与工具 fatal 的区别

`tool_gate` 阶段发现的问题通常尚未执行工具。此时推荐：

1. 写入拒绝观察。
2. 路由 `denied -> call_model`。
3. 让模型重新规划。

`tool_execute` 阶段发生 fatal error，说明工具执行时触发致命错误。此时推荐：

1. 写入 `final_answer`。
2. 路由 `fatal_error -> final_answer`。

---

## 22. 测试计划

测试不应依赖真实外部 LLM。模型节点使用 fake model 或 mock。

### 22.1 单元测试

| 测试文件                    | 内容                                                 |
| --------------------------- | ---------------------------------------------------- |
| `test_token_budget.py`      | token 预算计算、超限和未超限路由。                   |
| `test_tools_path_safety.py` | `../secret`、绝对路径、敏感路径拒绝。                |
| `test_tool_gate.py`         | 只读 allowed，写入 needs_approval，未知工具 denied。 |
| `test_graph_routes.py`      | 图节点存在、条件路由返回值正确。                     |
| `test_cli_approval.py`      | 模拟 interrupt payload 和 resume payload。           |

### 22.2 工具测试

必须覆盖：

1. `list_files` 能返回目录结构。
2. `search_files` 能按 glob 搜索。
3. `grep` 能找到文本命中。
4. `read_file` 支持行号范围。
5. `write_file` 的 `create_only` 遇到已有文件会失败。
6. `apply_patch` 对非法路径会拒绝。
7. `run_shell` 对危险命令会拒绝。
8. `load_skill_resource` 拒绝 skill 目录逃逸。

### 22.3 集成测试

使用 fake model 模拟以下流程：

1. 用户询问项目结构。
2. 模型请求 `list_files`。
3. `tool_gate` allowed。
4. `tool_execute` success。
5. `observe` 写入观察。
6. 模型输出纯文本最终回答。

另一个流程：

1. 用户要求写文件。
2. 模型请求 `write_file`。
3. `tool_gate` needs_approval。
4. 模拟用户拒绝。
5. 模型重新规划并给出 final JSON。

### 22.4 测试命令

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```

CI 建议：

```bash
uv sync --locked
uv run --locked pytest
uv run --locked ruff check .
```

---

## 23. 开发里程碑

### M0：项目脚手架

交付：

1. `pyproject.toml`
2. `uv.lock`
3. `src/terminal_code_agent/` 基础包结构
4. `.env.example`
5. `README.md` 初稿
6. `AGENTS.md`

验收：

```bash
uv sync
uv run python -m terminal_code_agent --help
```

### M1：配置、schema、state

交付：

1. `Settings`
2. `AgentState`
3. `ToolResult`
4. `ApprovalRequest`
5. 基础测试

验收：

```bash
uv run pytest tests/test_output_schema.py tests/test_token_budget.py
```

### M2：工具与安全运行时

交付：

1. 8 个 `@tool` 工具。
2. 路径安全检查。
3. 敏感路径拒绝。
4. 长输出截断。
5. 工具测试。

验收：

```bash
uv run pytest tests/test_tools_path_safety.py
```

### M3：提示词与 LLM 封装

交付：

1. `prompts.py`
2. `llm.py`
3. fake model 测试辅助。

验收：无需真实 API key，mock 测试通过。

### M4：LangGraph 节点和路由

交付：

1. 所有指定节点。
2. 所有指定边。
3. 条件路由函数。
4. checkpointer 集成。

验收：

```bash
uv run pytest tests/test_graph_routes.py
```

### M5：CLI 与 human approval

交付：

1. 终端对话循环。
2. interrupt 检测。
3. `Command(resume=...)` 恢复。
4. 审批 y/n/edit。
5. 决策信息输出。

验收：

1. 只读任务可完成。
2. 写入任务会审批。
3. 拒绝审批后 agent 能重新规划。

### M6：日志、文档、质量检查

交付：

1. JSON Lines 日志。
2. 脱敏和截断。
3. README 完整使用说明。
4. 全量测试通过。

验收：

```bash
uv run pytest
uv run ruff check .
```

---

## 24. README 应包含的内容

`README.md` 面向使用者，应包含：

1. 项目简介。
2. 安装 uv。
3. 初始化和同步依赖。
4. `.env` 配置说明。
5. 运行方式。
6. 示例对话。
7. 工具列表。
8. 人工审批机制。
9. 安全限制。
10. 日志位置。
11. 测试命令。
12. 常见问题。

运行说明示例：

```bash
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY 或其他 provider key
uv sync
uv run terminal-code-agent --workdir .
```

---

## 25. AGENTS.md 应强调的长期约束

`AGENTS.md` 面向 Codex 或其他代码 agent，应强调：

1. 不得删除或绕过指定 LangGraph 图结构。
2. 不得把工具拆到多个文件。
3. 不得用黑盒 agent 替代显式图。
4. 不得让工具访问 workdir 外部路径。
5. 不得无审批执行 `run_shell`、`write_file`、`apply_patch`。
6. 不得在日志中记录敏感信息。
7. 最终模型输出必须是 JSON。
8. 修改依赖必须使用 uv，并更新 `uv.lock`。
9. 测试命令必须使用 `uv run pytest`。
10. 代码中关键安全逻辑需要中文注释。

---

## 26. 安全限制说明

本项目是终端 code agent，不是完整安全沙箱。第一阶段安全策略只能降低误操作风险，不能抵抗恶意模型或恶意仓库。

必须明确限制：

1. `run_shell` 在用户本机执行命令，风险较高，必须审批。
2. 文件写入和 patch 会修改真实工作目录，必须审批。
3. 路径限制只约束工具实现，不能替代 OS 权限隔离。
4. 如果用于不可信仓库，建议在容器、虚拟机或受限用户下运行。
5. 生产环境应增加：容器沙箱、网络隔离、资源限制、命令 allowlist、审计存储和更严格的密钥扫描。

---

## 27. 完成标准

实现完成后必须满足：

1. `uv run terminal-code-agent --workdir .` 能启动终端对话。
2. `uv run python -m terminal_code_agent --workdir .` 也能启动。
3. 输入只读问题时，agent 能调用只读工具并返回最终文本。
4. 输入修改类问题时，agent 在 `apply_patch` 或 `write_file` 前触发 human approval。
5. 输入命令执行类问题时，agent 在 `run_shell` 前触发 human approval。
6. 拒绝审批后，agent 能把拒绝作为观察并重新规划或给出最终说明。
7. 最终回答是面向用户的纯文本。
8. 日志文件产生，并包含主要节点事件。
9. 工具全部在 `tools.py`，且全部使用 `@tool`。
10. 提示词模板全部在 `prompts.py`。
11. 模型配置全部来自 `.env` / 环境变量。
12. 所有路径访问限制在 `workdir` 内。
13. 敏感路径默认拒绝。
14. `uv run pytest` 通过。
15. `uv run ruff check .` 通过。
16. `README.md` 和 `AGENTS.md` 与实际实现一致。

---

## 28. 禁止事项

1. 不要把整个项目写成单文件脚本。
2. 不要跳过 LangGraph 自定义图。
3. 不要直接使用黑盒 agent 替代指定节点和路由。
4. 不要让工具访问 `workdir` 外部路径。
5. 不要在日志中记录密钥、token、完整 `.env` 或私钥。
6. 不要让 `run_shell` 无审批执行。
7. 不要让 `write_file` 或 `apply_patch` 无审批修改文件。
8. 不要用自然语言作为最终模型输出。
9. 不要在工具函数里调用 `input()` 等待审批。
10. 不要使用全局 `os.chdir()` 改变进程工作目录。
11. 不要删除用户已有代码，除非用户明确要求并经过审批。
12. 不要把工具函数分散到多个文件。
13. 不要手动编辑 `.venv` 或用 `pip install` 绕过 uv 项目依赖管理。

---

## 29. 参考实现片段索引

开发时建议优先按以下顺序实现：

1. `config.py`：`Settings`
2. `schemas.py`：所有 Pydantic schema
3. `state.py`：`AgentState`
4. `tool_runtime.py`：路径安全、敏感路径、JSON 返回、截断
5. `tools.py`：8 个工具
6. `tool_gate.py`：风险策略
7. `prompts.py`：提示词模板
8. `llm.py`：`build_chat_model`
9. `token_budget.py`：预算估算
10. `logging_utils.py`：JSON Lines 日志
11. `graph.py`：节点、路由、图构建
12. `cli.py`：终端循环和审批恢复
13. `tests/`：mock LLM 的单元和集成测试
14. `README.md`：用户文档

---

## 30. 官方文档参考

开发实现时优先查阅官方文档：

1. LangChain Python Tools：`@tool`、工具 schema、ToolRuntime、ToolMessage、Command。
2. LangChain Python Models：`ChatOpenAI`、tool calling、`bind_tools`。
3. LangGraph Graph API：`StateGraph`、state、reducers、节点、边和条件路由。
4. LangGraph Interrupts：`interrupt()`、checkpointer、`Command(resume=...)`、同一 `thread_id` 恢复。
5. uv Projects：`uv init`、`pyproject.toml`、`.venv`、`uv.lock`、`uv run`、`uv sync`。
