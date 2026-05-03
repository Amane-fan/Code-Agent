# 评测方案

## MVP 任务集

创建 10-20 个小型 workspace 或 fixture，覆盖以下场景：

- Python 单元测试失败，并能通过一行 bug fix 修复。
- 缺少输入校验。
- 行为不变的小型重构。
- 新增 CLI 参数及对应测试。
- 连续两轮对话中，第二轮能引用第一轮的结论。
- 使用 `/compact` 压缩旧轮次后，后续任务仍能读取 `<memory>` 摘要。
- 根据代码行为更新 README 或文档。

## 指标

- 任务成功率。
- 补丁应用后的测试通过情况。
- 修改文件数量。
- 工具调用次数。
- 人工介入次数。
- workspace 边界拦截次数。
- 模型 token 消耗、近似模型成本和延迟。

## 验收门槛

在称为可演示项目前，应满足：

- 运行完整单元测试。
- 使用 `code-agent --workspace <dir> --provider offline --no-session` 完成一次离线交互。
- 验证 `/memory`、`/compact`、`/clear` 在交互窗口内按预期工作。
- 验证同一交互窗口内的多轮运行写入同一份 JSON 日志，并出现在 `runs` 列表中。
- 验证普通任务和 `/compact` 的模型调用 token usage 会显示在 CLI，并写入 session JSON 顶层 `model_calls`。
- 验证 session JSON 的顶层 `model_calls` 和 `runs[*].model_calls` 只在每个会话第一次非空 `system_instructions` 出现时保留完整内容。
- 使用 OpenAI-backed 交互完成一次不应用补丁的问答。
- 在一次性 fixture 中生成补丁，分别验证输入 `n` 不应用、输入 `y` 应用。
- 验证 workspace 外路径和敏感路径补丁会被拒绝。
