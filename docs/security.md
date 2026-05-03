# 安全模型

## 默认保护

- 初始模型请求不自动包含 workspace 文件内容，文件内容只能通过工具 observation 进入历史。
- 文件工具会跳过常见依赖目录、构建目录、缓存目录、二进制文件和 VCS 目录。
- `.env`、`.npmrc`、`.pypirc`、私钥和凭据文件等敏感名称不会被读取或写入。
- 疑似密钥的值会在工具输出展示或存储前被脱敏。
- `run_shell` 每次执行前都必须由用户在 CLI 中确认。
- 所有文件工具和 shell 工具都以 `--workspace` 指定目录为边界。
- 模型配置、基础系统 prompt、工具注册表和 skills 来自 Code-Agent 项目自身，不读取目标 workspace 的 `.env`、prompt 文件或 `SKILL.md`。
- 启动上下文只包含 skill 元数据；每轮任务前的 selector 最多选择 3 个 skill，并把选中的完整 `SKILL.md` 注入主任务系统 instructions。
- `load_skill_resources` 只能读取已安装 skill 下 `references/` 或 `resources/` 中的附属 UTF-8 文本资料，不能读取 `SKILL.md`、根目录文件、目录或越界路径。

## 使用者责任

- 在确认 `run_shell` 前应审查模型请求执行的命令。
- 不要把 `.code-agent/` 提交到版本控制中，因为它可能包含任务 prompt、系统提示词、已选 skill 正文和运行历史。
- 为模型 Provider 使用最小权限 API key。

## 后续加固方向

- 为文件写入工具加入可选确认策略。
- 即使用户确认，也对明确破坏性的 shell 命令加入拒绝列表。
- 增加更细粒度的写入策略，例如只允许修改用户批准的子目录。
- 对写入内容增加密钥检测，避免把新密钥写入文件。
- 为项目级 skills 设计独立信任策略；当前默认不从目标 workspace 加载 skills。
