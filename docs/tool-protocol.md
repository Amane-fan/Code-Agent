# 工具协议

## 模型输出

每轮模型输出必须是以下两种之一：

```text
<summary>简短公开思路摘要</summary>
<action>{"tool":"read_file","args":{"path":"README.md"}}</action>
```

或：

```text
<summary>简短公开思路摘要</summary>
<final_answer>最终回答</final_answer>
```

`<action>` 内部必须是 JSON 对象，包含：

- `tool`：工具名称。
- `args`：参数对象。

模型输入中可能出现 `<memory>`，它表示当前终端窗口内较旧轮次的压缩摘要。`<memory>` 只作为输入
上下文使用，不是模型允许输出的标签。

## 工具返回结构

每个工具 observation 都会作为 `<observation>` 事件写回 LangGraph state 中的历史，并参与下一轮模型输入。
每个工具 observation 都包含：

- `name`：稳定的工具名称。
- `ok`：布尔成功标记。
- `output`：面向人的 stdout 风格输出。
- `error`：面向人的错误信息。
- `metadata`：结构化细节，例如路径、命令或 return code。

## 当前工具

工具清单由启动时的工具注册表动态生成，并注入系统 instructions。每个可调用工具都继承
`code_agent.tools.Tool`，声明稳定的 `name`、`description`、`parameters_schema`、`returns_schema`，
并实现 `run(args)`。启动时会自动发现并导入 `code_agent.tools` 包内模块，把其中的工具子类注册到
默认工具注册表。后续新增内置工具时，只需要在该包内新增工具类文件并提供这些字段和实现。

`parameters_schema` 和 `returns_schema` 使用 JSON Schema 风格的对象描述。当前框架把 schema 渲染给
模型作为调用协议说明；参数的业务校验仍由各工具实现自行完成。默认工具包括：

- `read_file({"path": "relative/path"})`：读取一个非敏感 UTF-8 文本文件。
- `write_file({"path": "relative/path", "content": "..."})`：创建或覆盖一个非敏感文本文件。
- `edit_file({"path": "relative/path", "old_text": "...", "new_text": "..."})`：要求 `old_text` 唯一匹配后替换。
- `list_files({})`：列出 workspace 中的非敏感文件。
- `grep_search({"pattern": "text"})`：在非敏感文件中执行大小写不敏感的文本搜索。
- `run_shell({"command": "..."})`：经用户确认后，在 workspace 下通过 `/bin/bash -lc` 执行命令。
- `load_skill_resources({"name": "skill_name", "paths": ["references/guide.md"]})`：读取已安装 skill 下 `references/` 或 `resources/` 中的附属 UTF-8 文本资料。

所有工具实现都绑定到启动时指定的 workspace 根目录。

## Skills

启动时，Code-Agent 从自身受控的 skills 目录加载 `SKILL.md` 元数据，并把可用 skill 的名称和描述注入
instructions。每轮主任务前会先执行一次独立的 `skill_selection` 模型调用，输入为当前用户问题、当前
窗口 memory、近期完整轮次和 skill 元数据，不读取 workspace 文件。

skill 元数据使用标签形式渲染，每个 `<skill>` 包含 `name` 和 `description`：

```text
<skills>
<skill>
  <name>skill_name</name>
  <description>When to use this skill.</description>
</skill>
</skills>
```

selector 必须返回严格 JSON：

```text
{"skills":["skill_name"]}
```

每轮最多加载 3 个已知 skill。未知名称会被忽略并记录；provider 为 `offline`、selector 调用失败或 JSON
非法时，不加载任何 skill，主任务继续执行。选中的完整 `SKILL.md` 会出现在主任务系统 instructions 的
`<loaded_skills>` 区块中。

`load_skill_resources` 只用于加载已选 skill 明确引用的附属资料。路径必须以 `references/` 或
`resources/` 开头，并且不能是绝对路径、包含 `..`、指向目录、缺失文件、`SKILL.md` 或 skill 根目录文件。
资源工具按请求顺序返回带标题的文本内容；任一文件失败时不会返回部分内容。
