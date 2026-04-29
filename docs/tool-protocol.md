# 工具协议

## 通用返回结构

每个工具都返回：

- `name`：稳定的工具名称。
- `ok`：布尔成功标记。
- `output`：面向人的 stdout 风格输出。
- `error`：面向人的错误信息。
- `metadata`：结构化细节，例如 argv 或 return code。

## 工具

- `file.list`：列出仓库中的非敏感文件。
- `file.read`：读取一个非敏感 UTF-8 文本文件。
- `file.search`：在非敏感文件中执行大小写不敏感的文本搜索。
- `shell.run`：默认只运行安全命令前缀。
- `patch.check`：使用 `git apply --check` 校验 unified diff。
- `patch.apply`：使用 `git apply` 应用已校验的 unified diff。

LangGraph 工作流会在确定性的图节点中调用这些工具。当前没有把它们暴露成由模型自由选择的
`ToolNode`，这样可以让 MVP 行为更可预测，并保留现有安全门。

## 补丁约定

模型 Provider 应尽量输出一个 fenced diff block：

```diff
diff --git a/path b/path
--- a/path
+++ b/path
@@ -1 +1 @@
-old
+new
```

如果补丁无法通过 `git apply --check`，Agent 会拒绝应用该补丁。
