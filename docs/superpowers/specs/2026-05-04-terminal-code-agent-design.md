# Terminal Code Agent 设计规格

## 背景

本仓库当前只有项目配置、README 和 `docs/development.md`。本次开发以 `docs/development.md` 为唯一实现规格；当现有项目配置与文档冲突时，以开发文档为准。

## 方案选择

采用文档推荐的显式 LangGraph 图方案，源码包命名为 `terminal_code_agent`，命令名为 `terminal-code-agent`。不沿用当前 `code_agent` 包名、脚本名或不完整配置。

可选方案对比：

1. 完整按文档实现显式图、集中工具、安全策略和 CLI。优点是满足完成标准，测试边界清晰；缺点是初次改动较大。
2. 在现有 `code_agent` 名称下兼容实现。优点是改动较少；缺点是与文档目录、命令和验收标准冲突。
3. 先实现工具层和测试，延后 CLI 与 LangGraph。优点是风险低；缺点是不能达到“项目开发完成”的要求。

最终选择方案 1。

## 架构

项目采用 Python、LangChain、LangGraph 和 uv。核心模块按文档拆分为配置、schema、state、工具运行时、工具、工具审批、提示词、LLM 初始化、token 预算、日志、图节点和 CLI。

LangGraph 使用自定义 `StateGraph(AgentState)`，包含文档指定的节点与条件路由：`init_state`、`skill_select`、`context_pack`、`budget_check`、`compact_context`、`call_model`、`repair_output`、`tool_gate`、`human_approval`、`tool_execute`、`observe`、`final_answer`。不使用黑盒 `create_react_agent`。

## 数据流

每轮 CLI 输入会生成 `thread_id`、`workdir` 和 `user_input`，进入 graph。`init_state` 追加用户消息；`skill_select` 读取 `skills/`；`context_pack` 打包历史和观察；`budget_check` 决定是否压缩；`call_model` 通过 LangChain 原生 tool calls 请求工具或输出最终 JSON。

工具调用先进入 `tool_gate`。只读工具默认允许；`write_file`、`apply_patch`、`run_shell` 默认触发 `human_approval`，审批节点使用 LangGraph `interrupt()`，由 CLI 使用 `Command(resume=...)` 恢复。

## 安全策略

所有文件工具通过 `resolve_in_root()` 限制在启动时指定的 `workdir` 内。敏感路径如 `.env`、私钥、SSH key、云凭据、包管理凭据默认拒绝。日志写入前递归脱敏并截断长文本。

`run_shell` 固定 `cwd=workdir`，拒绝文档列出的危险命令模式。第一阶段不是完整沙箱，README 会明确风险。

## 测试

测试不依赖真实 LLM。单元测试覆盖最终输出 schema、token 预算、路径安全、工具行为、工具审批、图路由和 CLI 审批 payload。集成测试使用 fake model 或直接节点状态验证只读工具与审批拒绝流程。

验收命令：

```bash
uv run pytest
uv run ruff check .
```

## 自检

本规格无待定项；范围限定为 `docs/development.md` 第一阶段要求；命名、目录、工具集中放置、显式图、审批和最终 JSON 均与开发文档一致。
