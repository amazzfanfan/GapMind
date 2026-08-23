# RAG 检索与生成优化方案

> 日期：2026-08-23<br>
> 状态：阶段 A 已完成；阶段 B-D 等待评测基线后分批执行<br>
> 范围：本地封版前的 Workspace Chat RAG；不部署、不引入重型 Agent 框架、不改变 HITL 边界。

## 1. 现状与结论

当前 Workspace Chat 是工作区隔离的稠密向量 RAG，不是 GraphRAG：

```text
论文上传
  → parse_pdf 解析和章节切块
  → chunks JSONL
  → embed_chunks Celery 任务
  → BGE-M3 稠密向量写入 Milvus

工作区内的普通提问
  → BGE-M3 查询向量
  → Milvus workspace_id 过滤召回
  → BGE reranker 重排
  → 论文证据 + 可选计划/报告/代码草案组成上下文
  → LLM 流式回答
  → 持久化 ChatMessageEvidence 与来源护照
```

普通 `/chat/new` 对话不绑定 workspace 时，不检索工作区论文。绑定 workspace 的普通 chat 每次发送消息都会执行一次上述检索。研究计划、报告、代码草案是可选上下文，不能替代论文证据。

知识图谱域已经维护 `KnowledgeItem`、`KnowledgeRelation`、实体和邻居查询，但 ChatService 不调用图谱查询；图谱当前用于可视化和人工探索，不参与问答上下文。因此不能把当前能力表述为 GraphRAG。

## 2. 目标与边界

### 目标

1. 保证所有 Chat LLM 调用使用 `disable_thinking=True`，符合项目硬性约定。
2. 把对话历史、计划、补充产物和论文证据纳入统一上下文上限，优先保留当前问题和最近有效历史。
3. 提升普通 Chat 的跨论文证据覆盖，避免同一论文多个 chunk 占满证据槽位。
4. 保持 workspace 隔离、NUL 防护、fail-closed 检索错误处理、来源分级和 `[E]/[P]/[D]/[C]` 引用边界。
5. 建立后续混合检索与条件式 GraphRAG 的可验证入口，而不是为“GraphRAG”标签扩张架构。

### 非目标

- 不在本轮引入图数据库、图向量库、独立 Agent 框架或自动执行代码。
- 不把知识图谱中的 AI 抽取关系直接当作论文事实引用。
- 不绕过人工确认 Gate，也不将报告或代码草案伪装为论文证据。
- 不在缺少评测集的情况下凭主观阈值淘汰论文证据。

## 3. 目标架构

```text
Chat question + selected workspace
  ├─ Context selection
  │   ├─ confirmed plan (optional)
  │   └─ confirmed report / unrun code draft (optional, same plan)
  ├─ Retrieval query planning
  │   ├─ original query (required)
  │   └─ later: deterministic method / baseline / section facets
  ├─ Dense retrieval
  │   ├─ BGE-M3 embedding
  │   ├─ Milvus workspace filter
  │   ├─ recall over-fetch
  │   └─ cross-encoder rerank
  ├─ Evidence assembly
  │   ├─ per-paper diversity
  │   ├─ immutable chunk offsets
  │   └─ paper-only [En] evidence
  ├─ Budgeted prompt
  │   ├─ immutable instructions + workspace profile
  │   ├─ clipped plan / artifacts / evidence
  │   ├─ newest conversation history
  │   └─ current user question (never dropped)
  └─ Generation and audit
      ├─ disable_thinking=True
      ├─ one bounded citation-quality repair in a later phase
      └─ persisted evidence and source manifest
```

## 4. 分阶段实施

### A. 本轮基线治理

| 编号 | 改动 | 验收标准 |
|---|---|---|
| A1 | Chat 同步和流式 LLM 调用统一关闭 thinking | 两条调用都显式传 `disable_thinking=True`，不传 `reasoning_effort` |
| A2 | 新增全局提示词字符预算；历史按最近优先保留 | 任何工作区问答的最终 messages 不超过配置上限；当前问题始终保留 |
| A3 | Chat semantic retrieval 启用按论文去重 | rerank 后最多一条最高分 chunk/论文，尽量给出 `top_k` 篇不同论文 |
| A4 | 补测试与文档记录 | 覆盖上述边界；既有 RAG、来源护照和失败分型测试继续通过 |

本轮不迁移数据库。预算配置仅修改应用 Settings，证据来源和现有 `chat_message_evidence` 结构保持不变。

### B. 回答可靠性与检索质量

1. 将现有引用检查从前端告警升级为受限质量门：发现失效 `[En]` 或已检索却没有论文引用时，最多进行一次受限修复；仍失败时明确标记证据不足，不伪造引用。
2. 为方法、损失函数、数据集、基线和比较类问题增加确定性分面检索与章节优先级；原始问题始终保留为主查询。
3. 在固定 retrieval Gold Set 和新增 Chat QA 集上校准最小相关性、覆盖率和“证据不足”阈值；不直接写死未经评测的分数门槛。
4. 在 ChatMessage 的审计字段或独立轻量快照中记录请求 ID、召回数、重排状态、耗时和最终论文数，便于定位质量与延迟问题。

### C. 混合检索

对专有名词、公式、损失函数和模型版本，稠密向量召回不稳定。验证后采用：

```text
Dense BGE-M3 recall + lexical/BM25 recall
  → reciprocal-rank fusion
  → cross-encoder rerank
  → per-paper diversity
```

实现应优先复用现有 Postgres 或 Milvus 能力，保持 workspace 过滤在召回层生效。引入前必须在固定 Gold Set 和真实演示问题上证明覆盖提升、无 workspace 泄漏、延迟可接受。

### D. 条件式 GraphRAG-lite

只有在以下问题上，才触发已有知识图谱的有限扩展：跨论文实体关系、术语归属、证据冲突、两跳溯源。

1. 从问题中匹配实体或关系候选。
2. 仅访问当前 workspace 中已确认且可回链 EvidenceSpan 的节点/关系。
3. 图只生成额外 chunk 候选或 rerank 特征，最终回答仍只引用论文 chunk `[En]`。
4. 找不到可靠图证据时无声回退为现有向量 RAG。

进入本阶段的前提：阶段 B/C 有评测基线；图谱确认状态、关系到 chunk 的映射和跨论文问答集已齐备。否则 GraphRAG 的噪声和维护成本高于收益。

## 5. 关键实现约束

- 所有 LLM 调用：`disable_thinking=True`，不得混用 `reasoning_effort`。
- 检索错误：embedding/Milvus/collection 失败保持 fail-closed，不调用 LLM；reranker 失败可使用向量结果并标记 degraded。
- 无论文命中：若没有计划/补充来源，直接返回证据不足；若存在计划来源，必须明确没有论文证据。
- 来源：论文使用 `[En]`；计划 `[Pn]`；确认报告 `[Dn]`；代码草案 `[Cn]`。后者永不作为论文事实。
- 安全：所有进入 PostgreSQL 文本/JSON 的检索内容继续去除 NUL；所有查询和来源均严格验证 workspace。
- 性能：避免对同一篇论文的每条证据重复读取 chunks JSONL；后续改为按论文批量解析或缓存。

## 6. 测试与验收

### 单元与 API 测试

- 普通对话不检索；绑定 workspace 的 Chat 必经 retrieval。
- 同步和流式调用均禁用 thinking。
- 上下文超预算时保留当前问题和最新历史，不超上限。
- Chat 多篇论文候选会去重；无命中、检索失败、reranker 降级行为不回归。
- 计划歧义、跨 workspace 计划、报告/代码来源分级、NUL 防护、引用一致性继续通过。

### 质量与性能指标

- 固定 retrieval Gate：semantic / similar / counter 指标不下降，workspace leakage 必须为 0。
- 新增 Chat QA 集：论文引用有效率、已检索但无引用率、独立论文覆盖数、证据不足判断准确率。
- 记录 P50/P95：embedding、Milvus、rerank、端到端首 token 延迟。

## 7. 执行顺序与提交纪律

先完成 A1-A4 并运行定向后端测试、完整后端测试、前端 typecheck/lint/test/build。随后汇报改动与剩余风险，等待用户明确指示后再 commit。阶段 B-D 分批执行，每一阶段先补评测再扩大能力；不部署、不 push。

## 8. 2026-08-23 阶段 A 实施记录

- A1：Chat 同步和 SSE 流式调用均已显式传入 `disable_thinking=True`，未传入 `reasoning_effort`。
- A2：新增总提示词预算 `chat_prompt_max_context_chars=48000`，并分别限制工作区资料、已确认计划和补充产物。历史上下文改为从最新已完成消息向前填充，当前问题始终保留。
- A3：`semantic_search` 新增内部可选的 `diversify_by_paper`。Chat 调用启用该参数，在 rerank 后保留每篇论文的最高分 chunk；对外检索 API 保持原有 chunk 级默认行为。
- A4：新增/更新 Chat 和 retrieval 测试，覆盖关闭 thinking、最近历史优先、总预算、工作区 Chat 的多论文去重。

验证结果：定向后端测试 `34 passed`；完整后端测试 `434 passed`；前端测试 `56 passed`；TypeScript 类型检查和生产构建通过；`npm run lint` 为 0 errors、14 条既有 warning。

阶段 B 的引用质量门、分面检索、阈值校准与可观测性，必须先补 Chat QA 评测集，不以未验证启发式改变论文证据边界。阶段 C/D 的混合检索和条件式 GraphRAG-lite 继续保持待评测状态。
