我想写一个终端code agent的python项目，使用 LangChain + LangGraph 框架
除了记忆管理功能，其他尽量使用LangChain/LangGraph原生的工具
需要支持以下功能：
需要支持多轮对话，启动项目时，需要指定agent的工作目录，用户提出问题后，使用react模式运行agent
agent编排方式使用LangGraph框架，以下是图的结构：

START
  -> init_state
  -> skill_select
  -> context_pack
  -> budget_check

budget_check -- ok --> call_model
budget_check -- over_limit --> compact_context -> context_pack

call_model -- tool_calls --> tool_gate
call_model -- final --> final_answer -> END
call_model -- invalid_output --> repair_output -> call_model

tool_gate -- allowed --> tool_execute
tool_gate -- needs_approval --> human_approval
tool_gate -- denied --> call_model

human_approval -- approved --> tool_execute
human_approval -- rejected --> call_model

tool_execute -- success --> observe -> context_pack
tool_execute -- retryable_error --> tool_repair -> call_model
tool_execute -- fatal_error --> final_answer -> END

各个节点的作用：
1. init_state: 初始化本轮 agent run 的状态。
2. skill_select: 根据用户本轮任务选择合适的skill加载进上下文，使用LLM实现
3. context_pack: 把当前 state 中的材料组装成下一次模型调用所需的上下文。
4. budget_check: 检查当前上下文是否超过模型 token budget。
5. compact_context: 压缩上下文
6. call_model: 调用LLM，决定下一步
7. repair_output: 当模型输出结果不符合格式是，尝试修复，需要设置最大重试次数
8. tool_gate: 判断模型请求的工具是否允许执行。
9. human_approval: 在人类审批点暂停，等待用户或开发者确认。
10. tool_execute: 执行工具
11. observe: 把工具执行结果转成 agent 可用的结构化观察。
12. tool_repair: 处理可恢复的工具错误
13. final_answer: 生成最终结果

提供的工具：
1. list_files: 查看目录结构
2. search_files: 按照文件名搜索
3. grep: 按文本内容搜索
4. read_file: 读取文件内容，支持按行号读取
5. apply_patch: 用patch修改文件
6. write_file: 创建/写入文件
7. run_shell: 运行shell命令
8. load_skill_resource: 读取某个skill目录下的资源信息，例如references

所有工具使用@tool修饰，并且放在一个文件中，需要有工具描述，参数信息和返回值信息

发送给大模型的系统提示词使用提示词模板

上下文信息存储在LangGraph的state节点中，每个对话需要有角色信息和信息内容，输出结果使用Json

需要有日志记录功能，记录agent的行为

写的代码需要有适当的中文注释

调用的模型信息使用.env文件中的配置

终端对话框中，需要输出agent的决策信息，例如调用了什么工具，对下一步行为的总结等