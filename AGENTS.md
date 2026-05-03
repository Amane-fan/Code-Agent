# AGENTS.md — Code Agent 项目开发指南

## 项目概览

Code Agent 是一个终端优先的 AI 编程 Agent，基于 LangGraph ReAct 工具循环实现代码阅读、文件修改、命令执行和多轮任务协作。所有文件和 shell 能力限制在 `--workspace` 指定的目录边界内，强调可审计、可控和可扩展。

### 核心模块

| 模块 | 路径 | 职责 |
|------|------|------|
| CLI | `src/code_agent/cli.py` | Typer + prompt_toolkit + Rich 交互终端 |
| Agent 门面 | `src/code_agent/agent.py` | 组装依赖、启动每次任务运行 |
| LangGraph Runner | `src/code_agent/react.py` | StateGraph 驱动模型调用、工具执行、上限保护 |
| Provider 层 | `src/code_agent/providers.py` | 封装 OpenAI-compatible chat model + 离线模式 |
| Prompt 构建 | `src/code_agent/prompting.py` | 动态拼接系统提示词、工具说明、skill 正文 |
| 会话管理 | `src/code_agent/conversation.py` | 多轮历史、压缩摘要、近期完整轮次 |
| 上下文组装 | `src/code_agent/context.py` | 压缩输入构建 |
| 工具注册 | `src/code_agent/tools/` | Tool 基类 + 自动注册 + 默认工具实现 |
| Skill 系统 | `src/code_agent/skills.py` | Skill 元数据发现、加载、资源读取 |
| Skill 选择 | `src/code_agent/skill_selection.py` | 每轮自动选择最多 3 个相关 skill |
| 会话日志 | `src/code_agent/session.py` | JSON 日志、token usage 记录 |
| 安全模块 | `src/code_agent/security.py` | 敏感路径过滤、密钥脱敏 |
| 系统提示词 | `src/code_agent/prompts/system.md` | 基础系统 prompt 模板 |
| MCP 示例 | `src/code_agent/mcp_server.py` / `mcp_client.py` | MCP 协议验证 |

详细架构说明见 `docs/architecture.md`。

---

## 开发环境

### 环境要求

- **Python**: `>=3.12`
- **包管理器**: [uv](https://docs.astral.sh/uv/)
- **操作系统**: Linux / macOS / WSL2

### 环境变量

配置从 Code Agent 项目自身的 `.env` 读取，不读取目标 workspace 的 `.env`：

```bash
API_KEY=你的API Key
BASE_URL=https://api.deepseek.com
MODEL=deepseek-v4-flash
```

### 运行

```bash
# 交互式启动
uv run python -m code_agent --workspace /path/to/target-project

### 测试与检查

```bash
# 运行测试
uv run pytest

# Lint 检查
uv run ruff check .

# 类型检查（strict 模式）
uv run mypy src

# 格式化
uv run ruff format .
```

---

## 技术栈

### 运行时依赖

| 依赖 | 用途 |
|------|------|
| `langgraph>=1.1` | Agent 编排框架，StateGraph 驱动 ReAct 循环 |
| `langchain-openai>=1.1` | OpenAI-compatible chat model 封装 |
| `prompt_toolkit>=3.0` | 交互式终端输入 |
| `rich>=13.7` | 格式化终端输出、事件流渲染 |
| `typer>=0.12` | CLI 参数解析 |
| `mcp>=1.0` | MCP 协议示例服务端/客户端 |

### 开发依赖

| 依赖 | 用途 |
|------|------|
| `pytest>=8.0` | 测试框架 |
| `ruff>=0.6` | Lint + 格式化（line-length=100，target=py312）|
| `mypy>=1.11` | 静态类型检查（strict 模式）|

### 构建系统

- **build-backend**: hatchling
- **wheel packages**: `src/code_agent`
- **入口脚本**: `code-agent`, `code-agent-mcp-server`, `code-agent-mcp-client`

---

## Agent 编排规范

### 优先使用 LangGraph

涉及**多步骤决策循环、条件分支、工具路由、状态管理**的 Agent 编排逻辑，优先使用 `langgraph` 实现。

### 工具循环协议

模型每轮返回 `<summary>` + `<action>`（调用工具）或 `<summary>` + `<final_answer>`（返回最终结果）。工具调用结果以 `<observation>` 形式进入历史，参与下一轮模型调用。必须保持此协议不变。

### Skill 选择流程

每轮任务前先执行 skill selection（独立模型调用），最多选择 3 个相关 skill，选中的完整 `SKILL.md` 注入主任务系统 instructions。失败时跳过继续主任务。

---

## 代码规范

### 中文注释

代码中的注释应使用**中文**，遵循以下原则：

- **必须加注释的场景**：非显而易见的逻辑、隐含约束、workaround、易误解的行为、安全相关判断。
- **可以不注释的场景**：命名已充分表达意图的常规代码、getter/setter、标准模式的调用。
- 注释风格：单行用 `#`，避免冗长的多行文档字符串。
- 注释应解释 **WHY** 而非 **WHAT**，代码本身说明了做什么。

```python
# 正确：解释为什么这样做
# 目标 workspace 的 .env 可能含有恶意变量，必须先从环境变量中清理后再启动 shell
os.environ.pop("ENV_FILE", None)

# 错误：重复代码已经说明的内容
# 从环境变量中删除 ENV_FILE
os.environ.pop("ENV_FILE", None)
```

### Python 编码规范

- 遵循 `ruff` 规则（line-length=100，target-version=py312）。
- 强制使用 `mypy --strict` 类型注解。
- 使用 `hatchling` 构建，包目录为 `src/code_agent`。
- 公开 API 保持向后兼容，私有 API 可自由重构。

### 安全编码

- 文件工具必须跳过 `.env`、私钥、凭据文件、`.git`、`.venv`、`node_modules` 等敏感路径。
- 疑似密钥值必须在展示/存储前脱敏。
- `run_shell` 每次执行前都必须要求用户确认。
- 工具操作不允许越出 `--workspace` 边界。
- Code Agent 自身配置（`.env`、系统 prompt、skills）与目标 workspace 严格隔离，不读取目标 workspace 的配置文件。

---

## Git 提交规范

采用简洁的 `<type>: <description>` 格式，description 优先使用中文，type 使用英文小写。

### type 类型

| type | 含义 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `optimize` | 优化、重构（不改功能） |
| `docs` | 文档变更 |
| `test` | 测试相关 |
| `chore` | 杂项（构建、依赖更新等） |

### 示例

```
feat: 添加读取references功能
fix: 修改系统提示词
optimize: 重构tools模块结构
docs: 更新架构说明文档
chore: 升级 langgraph 到 1.2
```

### 规则

- 提交信息简洁明了，一行即可。
- 不要在提交中混入无关改动。
- 不提交 `.env`、`.code-agent/`、`workspace/` 等已被 `.gitignore` 排除的文件。

---

## 禁止事项

2. **禁止引入其他编排框架**：不要使用 langchain LCEL chains、自定义状态机等替代 LangGraph 做 Agent 编排。
3. **禁止越界操作**：文件工具和 shell 工具不允许访问 `--workspace` 指定目录之外的路径。
4. **禁止自动执行 shell 命令**：`run_shell` 每次执行前必须经过用户确认，不得跳过。
5. **禁止读取敏感文件**：`.env`、私钥、`.git`、`.venv`、`node_modules` 等不得被文件工具读取或写入。
6. **禁止读取目标 workspace 的配置**：目标 workspace 的 `.env`、prompt 文件、`SKILL.md` 不应影响 Agent 行为。
7. **禁止输出密钥**：API Key、token、密码等敏感值在日志和终端输出中必须脱敏。
8. **禁止硬编码**：所有可配置值（API URL、模型名、路径等）应从环境变量或合理默认值获取。
9. **禁止提交敏感文件**：`.env`、`.code-agent/`、会话日志不得提交到版本控制。
10. **禁止破坏性命令**：`rm -rf`、`git reset --hard`、`git push --force` 等命令除非用户明确要求并确认，否则不得执行。
