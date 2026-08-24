# GapMind RAG 检索与生成优化 Todo List

> 日期：2026-08-24  
> 范围：本地封版前的 Workspace Chat RAG 检索、回答可靠性和评测收尾  
> 当前分支：`yx_dev`  
> 当前 HEAD：`da3a797 test: 纳入 Chat 检索审计观测指标`  
> 策略：先完成可重复的离线评测和本地闭环，再决定是否扩大检索能力；不部署、不 push。

## 1. 当前结论

### 1.1 已完成

- 阶段 A 基线治理：
  - 同步与流式 Chat LLM 调用均使用 `disable_thinking=True`。
  - 未传 `reasoning_effort`。
  - 对话历史、工作区资料、计划和补充产物受统一提示词预算约束。
  - 历史消息按最近完成消息优先保留，当前问题始终保留。
  - Chat 检索在 rerank 后按论文去重，避免单篇论文占满证据槽位。
- 阶段 B 首批回答可靠性：
  - 同步和流式回答共用一次有界引用质量门。
  - 失效 `[En]`、已召回论文但回答无论文引用、失效 `[Pn]/[Dn]/[Cn]` 时，最多追加一次边界修复。
  - 修复失败时返回明确的证据不足结果，不伪造引用、不新增检索结果。
  - `citation_quality` 通过 Alembic `0022_chat_citation_quality` 持久化。
- 阶段 B 真实评测基础：
  - `evaluation/chat/` 已具备 Gold schema、匿名观测快照、引用/来源一致性评分和 runner。
  - 已完成人工复核的 GNN 解释样本共 7 条，分为 v1 的 2 条和 v2 的 5 条。
  - v1 报告 `2/2` 覆盖、v2 报告 `5/5` 覆盖；两批机械检查、论文引用有效性、必需论文覆盖和人工结论准确率均为 `1.0`。
  - v1/v2 仍是产品相关的 `draft`，尚未升级为固定 `gold`。
- 阶段 B 可观测性：
  - `ChatMessage.retrieval_audit` 通过 Alembic `0023_chat_retrieval_audit` 持久化检索状态、召回数、返回 chunk 数、最终论文数、reranker 状态和延迟。
  - 匿名导出器和离线报告已支持这些字段；`request_id` 和本地 `message_id` 不进入匿名评测快照。
  - 本地新发送的 GIB 问题已验证真实审计：`succeeded`、召回 18、返回 4 个 chunk、最终 4 篇论文、reranker `applied`、延迟 `986.83 ms`。
- 当前验证基线：
  - 完整后端测试：`450 passed, 2 warnings`。
  - 前端测试：`56 passed`。
  - TypeScript 类型检查、生产构建通过。
  - ESLint：`0 errors`、`14 warnings`。

### 1.2 尚未完成

- 阶段 B 的确定性分面检索和章节优先级尚未接入生产 Chat。
- 阶段 B 的最小相关性、覆盖率和“证据不足”阈值尚未校准，也不能凭当前小样本写死阈值。
- v2 历史 5 条匿名候选快照不含 `retrieval_audit`，其审计覆盖率为 `0`；本轮已在 5 个独立新对话中重新获得带审计样本，新的本地 draft 报告审计覆盖率为 `1.0`。旧快照仍保留，不用新消息覆盖旧人工记录。
- 混合检索、BM25/词法召回、RRF 和 GraphRAG-lite 均未实现，且在阶段 B/C 评测基线完成前不得提前实现。
- 当前 Workspace Chat 仍是 workspace 隔离的稠密向量 RAG，不应宣传为 GraphRAG。

## 2. 工作边界与硬性约定

以下约定适用于本清单全部任务：

- 所有 LLM 调用必须显式使用 `disable_thinking=True`，不得传 `reasoning_effort`。
- 普通 Chat 只在绑定 workspace 时检索论文；独立模式不伪造工作区论文证据。
- 论文只能使用 `[En]`；计划使用 `[Pn]`；确认报告使用 `[Dn]`；代码草案使用 `[Cn]`。
- 计划、报告、代码草案不能替代论文证据，也不能把其中的 `[E]` 标记复制为当前消息的论文引用。
- 无论文证据时 fail closed：没有可用论文且没有合规补充来源时，明确返回证据不足，不调用 LLM 编造答案。
- 任何进入 PostgreSQL 查询或持久化文本的检索内容继续移除 `NUL` 字节 `\x00`。
- 数据必须严格按 `workspace_id` 隔离；不能跨 workspace 读取论文、计划、报告、代码或知识关系。
- AI 只能产生候选；研究机会、研究计划等关键资产必须经过 HITL 确认。
- 软删除，不硬删除；Timeline 只读；Task 由系统创建。
- `frontend/src/api/types/api.gen.ts` 由 OpenAPI 自动生成，不手写。
- 不修改固定 Gold Set 来“过评测”；产品相关样本和固定基准必须区分。
- 不触碰、不暂存、不提交：`deploy/`、根目录 `index.html`、比赛 PDF、`frontend/vite.config.js`、`frontend/tsconfig.node.tsbuildinfo`，除非用户明确授权。
- 修改完成并测试通过后先汇报，等待用户明确指示再 commit；push 必须单独授权。

## 3. Todo 总览

| 编号 | 工作包 | 当前状态 | 完成条件 |
|---|---|---|---|
| A-01 | 阶段 A 基线治理 | ✅ 已完成 | 关闭 thinking、提示词预算、最近历史优先、按论文去重及测试完成 |
| B-01 | 引用质量门 | ✅ 已完成 | 同步/流式共用有界修复、失败回退、审计和前端告警完成 |
| B-02 | Chat QA 真实样本 | ◐ 已完成第一批 | 7 条人工复核；v1/v2 仍为 draft；需继续补齐审计样本并复核 |
| B-03 | 检索审计快照 | ✅ 已完成基础实现 | `0023`、导出器和报告指标完成；历史消息需重新采样 |
| B-04 | 确定性分面检索 | ◐ 已完成查询规划骨架 | 纯函数规则已测试；仍需离线 A/B，默认不接入 Chat |
| B-05 | 章节优先级 | ☐ 待做 | 仅使用已存在 canonical section，不能凭空增加章节事实 |
| B-06 | 阈值校准与 Gold 冻结 | ☐ 待做 | 样本达到复核要求、指标可重复、人工确认后再冻结 |
| B-07 | 生成质量回归 | ◐ 基础完成 | 引用边界已有；需补齐同步/流式、无证据、降级和延迟回归矩阵 |
| C-01 | 混合检索 | ⏸ 暂缓 | B-04/B-06 完成且证明稠密召回存在稳定缺口后才启动 |
| D-01 | GraphRAG-lite | ⏸ 暂缓 | B/C 有基线、图证据可回链且有跨论文问答集后才启动 |
| R-01 | 本地封版回归 | ◐ 持续 | 每个代码批次完成相关测试、完整后端测试；涉及前端再跑前端全套 |

## 4. 阶段 B：真实评测与回答可靠性

### B-02. Chat QA 样本补齐和复核

目标：让每条样本同时具备真实回答、真实论文证据、人工结论和可选检索审计，仍不调用 LLM 重写历史答案。

- [ ] B-02-01 建立样本目录，至少覆盖以下问题族：
  - [ ] 方法定义和经典方法列表。
  - [ ] 损失函数、优化目标和公式解释。
  - [ ] 数据集、实验设置和评价指标。
  - [ ] 基线、比较和相对优势。
  - [ ] 证据不足、过强全称断言和分布偏移问题。
  - [ ] 需要确认计划上下文的问题，验证 `[Pn]` 与论文 `[En]` 的边界。
- [ ] B-02-02 每个问题只从本地已持久化的 completed assistant message 导出；不从回答文本反推 Gold。
- [ ] B-02-03 导出时默认匿名化：`message_id=null`，不带 request id，不带数据库内部路径。
- [ ] B-02-04 人工填写 `human_verdict`：`supported`、`insufficient_evidence` 或 `unsupported`；未确认前保留 `null`。
- [ ] B-02-05 对 `supported` 题逐篇确认必需论文；对 `insufficient_evidence` 题不预置必需论文。
- [ ] B-02-06 至少完成第二位人工复核后，才把 draft Gold 改为 `gold`；不得因为机械指标为 `1.0` 自动冻结。
- [ ] B-02-07 对每条新样本确认 `retrieval_audit` 是否存在；旧消息审计为空时标记为“无运行时审计”，不能补写。

验收：

- 观测快照中的回答、证据 rank、论文标题和来源标记均来自真实持久化消息。
- `human_verdict` 有明确人工来源；没有人工判断的字段保持空值。
- `run_eval.py` 对完整样本返回 `0`，但报告仍明确显示样本规模和 annotation status。
- 报告同时给出机械指标、人工覆盖率、人工一致率和审计覆盖率；不输出未经验证的生产阈值。

### B-03. 检索审计与可观测性补齐

- [x] B-03-01 `ChatMessage.retrieval_audit` 迁移和 API schema 已完成。
- [x] B-03-02 失败路径保存稳定 diagnostic code，不保存 provider 原始异常。
- [x] B-03-03 匿名导出器保留状态、诊断码、召回数、chunk 数、论文数、reranker 和延迟。
- [x] B-03-04 离线报告支持审计覆盖率、状态分布、reranker 分布和 P50/P95/最大延迟。
- [x] B-03-05 对 v2 全部问题重新产生带 `retrieval_audit` 的真实消息；5 个问题均在独立新对话中完成，状态均为 `succeeded`、reranker 均为 `applied`。
- [x] B-03-06 将每条问题的检索审计和回答证据放在同一份本地报告中；报告为 `gnn_explanations_v2_audited_report.json`，不写入 Gold，不覆盖人工 verdict。
- [x] B-03-07 形成一次基线报告：主查询、最终论文数、已检索无引用比例、人工证据不足判断和端到端延迟。

本轮真实审计基线：5/5 观测覆盖，5/5 检索成功，5/5 reranker `applied`，召回数均为 `18`，最终论文数为 `4–6`，检索延迟 P50=`953.07 ms`、P95=`1250.67 ms`，已检索但无论文引用率为 `0.0`。用户确认 `chat-gnn-03` 至 `chat-gnn-06` 为 `supported`，`chat-gnn-07` 为 `insufficient_evidence`；q07 的理由是当前工作区没有直接回答“分布偏移下 GNN 解释稳定性”的充分论文证据，回答明确要求补充研究或实验。最终人工 verdict 覆盖率和准确率均为 `1.0`，但 v2 仍保持产品相关 `draft`，不自动升级为固定 Gold。

建议记录的指标：

- 检索状态：`succeeded`、`degraded`、`failed`。
- 召回候选数 `recall_count`。
- 最终返回 chunk 数 `returned_chunk_count`。
- 独立论文数 `final_paper_count`。
- reranker 状态：`applied`、`enabled_no_rerank`、`degraded`、`disabled`、`unknown`。
- 检索耗时 P50/P95/最大值。
- 回答证据指标：论文引用有效率、必需论文覆盖率、已检索但无论文引用比例、人工 `insufficient_evidence` 准确率。

注意：这些指标是诊断和比较工具，不等同于事实正确性，也不直接作为自动阈值。

### B-04. 确定性分面检索 A/B 实验

目标：针对方法、损失/公式、数据集/实验、基线/比较问题，验证查询分面是否改善论文覆盖，而不是先把启发式直接放进生产路径。

#### B-04-1 查询规划

- [x] 已新增纯函数 `backend/app/domains/chat/retrieval_facets.py`；不调用 LLM、embedding、Milvus 或数据库，当前不改变生产 Chat 行为。
- [x] 规划器保留原始问题作为 primary query，任何 facet 都不能替换或删除原问题。
- [x] 设计纯确定性、可审查的 facet 规则：
  - [x] 方法：`method / approach / mechanism / 方法 / 机制`。
  - [x] 损失与公式：`loss / objective / formula / equation / 损失 / 公式 / 优化目标`。
  - [x] 数据集与实验：`dataset / benchmark / experiment / evaluation / 数据集 / 基准 / 实验`。
  - [x] 基线与比较：`baseline / comparison / compare / 基线 / 对比 / 比较`。
- [x] 规则由单元测试覆盖，不能调用 LLM 生成查询 facet；当前定向测试 `19 passed`。
- [ ] 接入后再控制额外 query 数量，并记录额外 embedding、Milvus、reranker 调用和延迟。
- [x] section hint 只使用现有 canonical section，例如 `Method`、`Experiment`、`Related Work`；不得把 hint 当作论文事实。

#### B-04-2 候选合并

- [ ] 只在 workspace 过滤生效的召回层执行 facet query。
- [ ] 合并前按 `chunk_id` 去重；合并后继续按论文保留最高分 chunk。
- [ ] primary 和 facet 结果的来源、chunk offset、paper id 必须完整保留。
- [ ] primary 失败时仍 fail closed；facet 单独失败时不得伪造成功，应记录 degraded 诊断。
- [ ] 记录 facet 类型、query 数、各 query 召回数和合并后论文数，供 A/B 报告使用。
- [ ] 不通过任意未经评测的分数阈值删除论文证据。

#### B-04-3 离线 A/B 验收

- [x] 新增只读实验 runner `evaluation/retrieval/run_chat_facet_ab.py`，明确标记 `production_enabled=false`、`llm_called=false`、`workspace_mutated=false`。
- [ ] 在固定 retrieval Gold Set 上跑 primary-only 与 primary+facet 两组结果。
- [x] 在 Chat QA draft 上比较必需论文覆盖、独立论文数、回答中有效引用覆盖和人工证据不足判断；本轮使用 5 条带审计真实样本。
- [ ] 检查 workspace leakage 必须为 `0`。
- [x] 记录额外延迟、reranker 降级率和空结果变化；本轮 5/5 检索成功、5/5 reranker `applied`。
- [ ] 只有在覆盖提升或明确解决已人工确认的缺口，且无安全/隔离回归时，才提出启用方案。
- [ ] 若没有稳定收益，保留 planner 作为实验工具，不接入默认 Chat。

本轮 A/B 实验报告为 `evaluation/retrieval/reports/chat_gnn_facet_ab_draft_unsandboxed.json`。embedding、Milvus 和 reranker 恢复后，primary-only 的必需论文平均覆盖为 `1.0`，primary+facet 为 `0.875`；5 个问题中 facet 提升 `0` 条、回归 `1` 条。回归发生在 `chat-gnn-03`：方法 facet 将必需的 `Self-Interpretable Graph Learning with Sufficient and Necessary Explanations` 排出 top-k，覆盖从 `1.0` 降至 `0.5`；四个带 facet 问题平均增加约 `794.15 ms`。因此当前结论是保持 facet 默认关闭，不能据此接入生产 Chat，也不能把方法 facet 宣称为质量提升。

此前的受限网络运行曾将 5 个 primary query 分型为 `embedding_unavailable`；该结果保留在本地失败报告中，但不作为质量结论。后续 A/B 必须优先确认 embedding 可达，再比较检索结果。

### B-05. 章节优先级

- [ ] 先统计真实语料中 `Method`、`Experiment`、`Related Work` 等 canonical section 的可用比例。
- [ ] 不对缺少章节标记的 chunk 做硬过滤；只能作为查询 hint、排序特征或诊断信息。
- [ ] 公式/损失问题优先观察 `Method` 和 `Related Work`，但不能丢弃真实命中的其他章节。
- [ ] 数据集/实验/基线问题优先观察 `Experiment`，同时保留 `Method` 或 `Related Work` 中的定义证据。
- [ ] 章节优先级必须与每论文去重、workspace filter、NUL 防护和来源护照测试一起验收。
- [ ] 若章节 hint 导致必需论文召回下降，默认关闭并记录原因。

### B-06. 阈值校准与 Gold 冻结

- [ ] 先区分三个概念：检索相关性阈值、证据覆盖阈值、回答“证据不足”判断。
- [ ] 不把 reranker 分数直接当作证据覆盖，也不把 `confidence` 当作 Evidence Passport。
- [ ] 汇总固定 retrieval Gold、Chat QA draft 和真实审计样本后，再计算候选阈值。
- [ ] 对每个候选阈值记录 false positive：把相关但不足的证据当成可回答；记录 false negative：已有足够证据却误报不足。
- [ ] 由人工确认阈值语义和错误代价；自动 runner 只计算，不自动批准。
- [ ] Gold 冻结前完成双人复核、版本号、corpus/chunk/embedding/reranker freeze 信息。
- [ ] Gold 冻结后，产品相关 draft 可以继续新增，但不得回写或修改固定 Gold。
- [ ] 阈值接入代码前先加入边界测试：无命中、单篇命中、多篇命中、reranker degraded、跨 workspace、引用缺失。

### B-07. 生成可靠性回归

- [x] 同步/流式 `disable_thinking=True` 已覆盖。
- [x] 论文、计划、报告、代码草案来源边界已落地。
- [x] 引用一致性质量门和失败回退已落地。
- [ ] 增加同步/流式成对回归样本：相同检索结果下，来源边界和证据不足表述一致。
- [ ] 增加“已检索但无引用”“失效 `[En]`”“失效 `[Pn]/[Dn]/[Cn]`”“无论文命中”“reranker degraded”样本。
- [ ] 验证修复调用仍是一次上限，且修复调用同样 `disable_thinking=True`、不传 `reasoning_effort`。
- [ ] 验证失败回退不会写入不存在的 citation/evidence，不覆盖原始检索结果。
- [ ] 记录首 token、完成延迟、prompt 字符数、输出 token 和质量门状态；敏感内容不进入报告。
- [ ] 生成侧指标必须和人工事实判断分开，不用结构性引用通过代替事实正确。

## 5. 阶段 C：混合检索（暂缓）

只有阶段 B 证明专有名词、公式、损失函数或模型版本存在稳定的稠密召回缺口，才启动以下任务：

- [ ] C-01 明确缺口样本和基线结果，禁止凭单个问题引入混合检索。
- [ ] C-02 选择词法检索实现，优先复用现有 PostgreSQL 能力；先评估索引、迁移和 NUL 安全影响。
- [ ] C-03 实现 workspace-scoped lexical recall，验证软删除和 workspace filter 不泄漏。
- [ ] C-04 实现 Dense + lexical 的 RRF 合并，记录每种来源的 rank 和审计信息。
- [ ] C-05 统一进入现有 cross-encoder rerank 和按论文去重流程。
- [ ] C-06 对比 dense-only、lexical-only、hybrid 三组 recall@K、MRR、论文覆盖、引用覆盖、延迟和降级率。
- [ ] C-07 加入无索引、词法服务失败、空结果、NUL、跨 workspace 和 reranker 失败测试。
- [ ] C-08 只有 A/B 结果通过人工复核和完整回归后，才考虑默认启用；否则保留 feature flag 关闭。

不得在阶段 C：

- [ ] 不引入图数据库、微服务、K8s 或重型 Agent 框架。
- [ ] 不用词法命中直接成为论文事实；仍须经过统一 evidence materialization 和 `[En]` 引用链。
- [ ] 不绕过现有 Milvus workspace 过滤。

## 6. 阶段 D：条件式 GraphRAG-lite（暂缓）

进入条件全部满足后才开始：

- [ ] 阶段 B/C 有可重复的 retrieval 和 Chat QA 基线。
- [ ] 图谱节点、关系均能回链当前 workspace 的 `EvidenceSpan`/论文 chunk。
- [ ] 已有人工复核的跨论文实体关系、术语归属、证据冲突或两跳溯源问题集。
- [ ] 已明确图谱确认状态，未确认 AI 抽取关系不能直接作为事实。

实施顺序：

- [ ] D-01 从问题中确定性匹配实体/关系候选，记录匹配原因。
- [ ] D-02 只读取当前 workspace 且可回链证据的确认节点和关系。
- [ ] D-03 图谱只生成额外 chunk 候选或 rerank feature，不直接生成回答事实。
- [ ] D-04 最终回答仍只允许论文 chunk `[En]`；计划/报告/代码来源继续分级。
- [ ] D-05 图谱证据不足或服务失败时无声回退到现有 dense/hybrid RAG。
- [ ] D-06 对图谱启用、图谱回退、跨 workspace、未确认关系、断链 EvidenceSpan 加测试。
- [ ] D-07 对比 vector-only、hybrid、GraphRAG-lite 的覆盖、错误率、延迟和人工可解释性。

不得在阶段 D：

- [ ] 不把 `KnowledgeRelation` 的抽取结果直接当作论文事实。
- [ ] 不新增独立图数据库作为本地封版前置条件。
- [ ] 不因“GraphRAG”标签自动扩大架构或 Agent 数量。

## 7. 本地回归与交付清单

### 7.1 每个后端改动批次

- [ ] 运行相关测试，例如：

```powershell
cd D:\MyCode\Spark-competition\refactor\GapMind\backend
.venv\Scripts\python.exe -m pytest tests\test_chat_api.py tests\test_chat_qa_evaluation.py -q
```

- [ ] 运行完整后端测试：

```powershell
.venv\Scripts\python.exe -m pytest tests\ -q
```

- [ ] 如果改了 migration，检查并升级本地数据库：

```powershell
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\alembic.exe current
```

- [ ] 检查 `git diff --check`。
- [ ] 检查受保护路径未出现在 staged diff。
- [ ] 汇报测试和剩余风险，等待用户明确 commit。

### 7.2 涉及 API/schema 的改动

- [ ] 重新生成 OpenAPI 类型：

```powershell
cd D:\MyCode\Spark-competition\refactor\GapMind\frontend
npm run gen:api
```

- [ ] 运行完整前端检查：

```powershell
npm run test -- --run
npm run typecheck
npm run lint
npm run build
```

- [ ] 不手写 `frontend/src/api/types/api.gen.ts`。
- [ ] 前端检查产生的 `frontend/vite.config.js`、`frontend/tsconfig.node.tsbuildinfo` 不得被暂存。

### 7.3 真实本地 Chat 观测

- [ ] 确认后端已加载最新 migration 和代码。
- [ ] 在 Demo workspace 发送一条新问题，等待 assistant completed。
- [ ] 只读读取 Chat detail，确认 `retrieval_audit`、citations、source manifest 和 grounding 状态。
- [ ] 用导出器生成匿名快照；默认不带 `message_id`。
- [ ] 人工确认前保持 `human_verdict=null`；确认后再单独编辑评测副本。
- [ ] 不修改 workspace 论文、消息、Gold 或固定评测结果来修复输入。

## 8. 本地封版 DoD

RAG/生成优化达到本地封版条件，需要同时满足：

- [ ] 阶段 A 全部测试仍通过。
- [ ] 阶段 B 的 citation quality gate、Chat QA、retrieval audit 和生成回归均有可重复报告。
- [ ] Chat QA 至少覆盖支持、证据不足、失效引用、计划/报告/代码来源边界和 reranker degraded。
- [ ] 新增样本的审计覆盖率达到预先约定的人工复核范围；旧消息缺少审计时已明确标注。
- [ ] 确定性分面检索若启用，必须有 primary-only 对照、检索指标、延迟、隔离和人工复核结果；否则保持关闭。
- [ ] 没有未经评测的相关性阈值、证据不足阈值或自动事实判断。
- [ ] 不把 draft Gold、机械 `mechanical_passed` 或 citation validity 等同于事实正确率。
- [ ] 阶段 C/D 的延期状态和启动条件已记录。
- [ ] 完整后端测试通过；涉及前端时，前端测试、类型检查、lint、build 全部通过。
- [ ] 所有改动经过用户审查后再提交；没有部署和 push。

## 9. 风险与停止条件

遇到以下情况，应停止扩大能力并回到评测或人工确认，不得用启发式掩盖：

- [ ] facet query 使必需论文覆盖下降、workspace leakage 非零或引用链断裂。
- [ ] reranker/embedding/Milvus 失败导致无法区分“无证据”和“检索故障”。
- [ ] 只能依赖 LLM 判断某篇论文是否支持问题，但没有可回链 chunk 或人工复核。
- [ ] 评测样本没有真实持久化回答、真实 citation 或明确 human verdict。
- [ ] Gold 需要修改才能通过机械检查。
- [ ] 需要访问服务器 Ollama、部署目录或 push 才能完成本地验收。
- [ ] 需要硬删除历史消息、任务或 Timeline 才能清理演示数据。

## 10. 推荐接手顺序

1. 完成 B-02-05 至 B-03-07：补齐带审计的真实样本和基线报告。
2. 完成 B-04-01 的纯函数查询规划与单元测试，但默认不启用。
3. 在 retrieval Gold 和 Chat QA 上运行 primary-only vs facet A/B。
4. 根据 A/B 结果决定 B-04/B-05 是否进入默认 Chat；无稳定收益则保持关闭。
5. 完成 B-06 的人工复核和 Gold 冻结准备；在此之前不写生产阈值。
6. 完成 B-07 生成同步/流式回归和延迟观测。
7. 只有阶段 B 关闭后，重新评估是否需要阶段 C；阶段 D 继续等待图证据链和问答集。
8. 最后执行本地封版回归、文档交接和用户审查；不部署、不 push。
