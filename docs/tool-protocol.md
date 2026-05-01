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

每个工具 observation 都包含：

- `name`：稳定的工具名称。
- `ok`：布尔成功标记。
- `output`：面向人的 stdout 风格输出。
- `error`：面向人的错误信息。
- `metadata`：结构化细节，例如路径、命令或 return code。

## 当前工具

工具清单由启动时的工具注册表动态生成，并注入系统 instructions。默认工具包括：

- `read_file({"path": "relative/path"})`：读取一个非敏感 UTF-8 文本文件。
- `write_file({"path": "relative/path", "content": "..."})`：创建或覆盖一个非敏感文本文件。
- `edit_file({"path": "relative/path", "old_text": "...", "new_text": "..."})`：要求 `old_text` 唯一匹配后替换。
- `list_files({})`：列出 workspace 中的非敏感文件。
- `grep_search({"pattern": "text"})`：在非敏感文件中执行大小写不敏感的文本搜索。
- `run_shell({"command": "..."})`：经用户确认后，在 workspace 下通过 `/bin/bash -lc` 执行命令。
- `load_skill({"name": "skill_name"})`：按名称加载启动时列出的完整 `SKILL.md` 内容。

所有工具实现都绑定到启动时指定的 workspace 根目录。

## Skills

启动时，Code-Agent 从自身受控的 skills 目录加载 `SKILL.md` 元数据，并把可用 skill 的名称和描述注入
instructions。完整 skill 正文不会在启动时进入上下文。

如果模型判断需要某个 skill，应先调用：

```text
<action>{"tool":"load_skill","args":{"name":"skill_name"}}</action>
```

工具 observation 的 `output` 会包含完整 skill 内容。未知 skill 会返回 `ok=false`，并在 metadata 中列出
可用名称。
