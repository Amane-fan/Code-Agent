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

## 工具返回结构

每个工具 observation 都包含：

- `name`：稳定的工具名称。
- `ok`：布尔成功标记。
- `output`：面向人的 stdout 风格输出。
- `error`：面向人的错误信息。
- `metadata`：结构化细节，例如路径、命令或 return code。

## 当前工具

- `read_file({"path": "relative/path"})`：读取一个非敏感 UTF-8 文本文件。
- `write_file({"path": "relative/path", "content": "..."})`：创建或覆盖一个非敏感文本文件。
- `edit_file({"path": "relative/path", "old_text": "...", "new_text": "..."})`：要求 `old_text` 唯一匹配后替换。
- `list_files({})`：列出 workspace 中的非敏感文件。
- `grep_search({"pattern": "text"})`：在非敏感文件中执行大小写不敏感的文本搜索。
- `run_shell({"command": "..."})`：经用户确认后，在 workspace 下通过 `/bin/bash -lc` 执行命令。

所有工具实现都绑定到启动时指定的 workspace 根目录。
