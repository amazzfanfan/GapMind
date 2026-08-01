# Chat 与未来 Agent 的扩展边界

当前 Chat 是全局普通对话功能：`Router -> ChatService -> LLMGateway -> DeepSeek`。它只保存用户和 assistant 消息，不执行工具调用，不检索课题知识，也不访问互联网。

未来若需要扩展，应在 ChatService 与 LLMGateway 之间增加可替换的会话运行器，例如 `PlainChatRunner`、`RetrievalRunner` 和 `AgentRunner`，而不是把检索或工具逻辑直接塞进 ChatService。

可以预留的方向包括：

- 会话模式字段，用于区分普通对话、课题上下文和 Agent。
- 课题空间上下文，以及明确的用户授权范围。
- Knowledge/RAG 检索、消息引用和来源展示。
- 工具调用、任务状态和可审计的执行记录。
- SSE 流式输出、停止生成和消息分支。
- 多用户身份、权限与历史数据隔离。

以上内容不属于本次交付，当前页面会明确提示用户这是普通 AI 对话。
