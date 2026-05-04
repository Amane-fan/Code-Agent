# AGENTS.md

## 长期约束

- 默认使用简体中文沟通；代码、命令、API 名称、错误信息和文件名可以保留英文。
- 不得删除或绕过 `docs/development.md` 指定的 LangGraph 显式图结构。
- 不得使用黑盒 agent 替代自定义节点和路由。
- 所有暴露给模型的工具函数必须集中在 `src/terminal_code_agent/tools.py`，并使用 `@tool` 修饰。
- 文件系统工具不得访问启动时指定的 `workdir` 外部路径。
- `run_shell`、`write_file`、`apply_patch` 默认必须经过人工审批。
- 不得在日志中记录密钥、token、完整 `.env`、私钥或其他敏感信息。
- 最终模型输出必须是合法 `FinalAnswer` JSON，不能使用自然语言替代。
- 修改依赖必须使用 uv，并更新 `uv.lock`。
- 测试命令必须使用 `uv run pytest`。
- 关键安全逻辑、图路由、上下文压缩、人工审批和工具错误处理需要适量中文注释。
