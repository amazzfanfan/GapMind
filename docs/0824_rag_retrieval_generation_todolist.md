# GapMind RAG 检索与生成优化 Todo List

> 日期：2026-08-24  
> 范围：本地封版前的 Workspace Chat RAG 检索、回答可靠性和评测收尾  
> 当前分支：`yx_dev`  
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
  - 已完成人工复核的 GNN 解释样本共 9 条，分为 v1 的 2 条、v2 的 5 条和 v3 的 2 条。
  - v1 reviewer2 报告 `2/2` 覆盖、人工结论准确率 `1.0`，v2 reviewer2 报告 `5/5` 覆盖、人工结论准确率 `1.0`；两批机械检查和论文引用有效性均为 `1.0`。
  - v1/v2 已完成第二位人工复核；经用户确认，已分别创建 `gnn_explanations_gold_v1.json` 和 `gnn_explanations_gold_v2.json`，draft 原文件保留不变。
- 阶段 B 可观测性：
  - `ChatMessage.retrieval_audit` 通过 Alembic `0023_chat_retrieval_audit` 持久化检索状态、召回数、返回 chunk 数、最终论文数、reranker 状态和延迟。
  - 匿名导出器和离线报告已支持这些字段；`request_id` 和本地 `message_id` 不进入匿名评测快照。
  - 本地新发送的 GIB 问题已验证真实审计：`succeeded`、召回 18、返回 4 个 chunk、最终 4 篇论文、reranker `applied`、延迟 `986.83 ms`。
- 当前验证基线：
  - 完整后端测试：`469 passed, 2 warnings`。
  - 前端测试：`56 passed`。
  - TypeScript 类型检查、生产构建通过。
  - ESLint：`0 errors`、`14 warnings`。

### 1.2 尚未完成

- 阶段 B 的确定性分面检索和章节优先级已完成离线验收，但按结果保持关闭，不接入生产 Chat。
- 阶段 B 不批准生产相关性、覆盖率或“证据不足”数值阈值；k=15 仅保留为诊断观察点，`insufficient_evidence` 继续由人工确认。
- v2 历史 5 条匿名候选快照不含 `retrieval_audit`，其审计覆盖率为 `0`；本轮已在 5 个独立新对话中重新获得带审计样本，新的本地 draft 报告审计覆盖率为 `1.0`。旧快照仍保留，不用新消息覆盖旧人工记录。
- 混合检索、BM25/词法召回、RRF 和 GraphRAG-lite 均未实现，且在阶段 B/C 评测基线完成前不得提前实现。
- 当前 Workspace Chat 仍是 workspace 隔离的稠密向量 RAG，不应宣传为 GraphRAG。
- 本轮新增的 B-04/B-05 离线证据仍保持生产关闭：facet A/B 在真实 Chat QA draft 上出现一次回归，章节标记在当前语料中高度稀疏，不能直接作为硬过滤。

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
| B-02 | Chat QA 真实样本 | ✅ v1/v2 Gold 冻结，v3 draft 完成 | 9 条人工复核样本；v3 两条新增真实样本审计完整；v3 不自动升级为 Gold |
| B-03 | 检索审计快照 | ✅ 已完成基础实现 | `0023`、导出器和报告指标完成；历史消息需重新采样 |
| B-04 | 确定性分面检索 | ✅ 离线 A/B 完成，生产关闭 | runner、来源/偏移快照、失败/降级审计和固定 Gold 对照完成；真实 Chat QA 出现回归，保持默认关闭 |
| B-05 | 章节优先级 | ✅ 语料审计完成，生产不启用 | 已统计当前 canonical section 覆盖；章节 hint 仅作诊断，不做硬过滤 |
| B-06 | 阈值校准与 Gold 冻结 | ✅ 完成，无生产阈值 | Gold 已冻结、k=15 完整 Gate 为 FAIL；用户确认不批准生产数值阈值 |
| B-07 | 生成质量回归 | ✅ 完成 | 同步/流式字段、迁移、API 类型、真实运行时观测和聚合报告均完成 |
| C-01 | 混合检索 | ⏸ 暂缓 | B-04/B-06 完成且证明稠密召回存在稳定缺口后才启动 |
| D-01 | GraphRAG-lite | ⏸ 暂缓 | B/C 有基线、图证据可回链且有跨论文问答集后才启动 |
| R-01 | 本地封版回归 | ✅ 本地回归完成，待用户审查 | 相关测试、完整后端测试、迁移、OpenAPI 和前端全套检查均完成；不自动 commit |

## 4. 阶段 B：真实评测与回答可靠性

### B-02. Chat QA 样本补齐和复核

目标：让每条样本同时具备真实回答、真实论文证据、人工结论和可选检索审计，仍不调用 LLM 重写历史答案。

- [x] B-02-01 建立样本目录并覆盖以下问题族；v3 新增的数据集/实验题和基线/比较题均来自本地持久化 completed assistant message：
  - [x] 方法定义和经典方法列表。
  - [x] 损失函数、优化目标和公式解释。
  - [x] 数据集、实验设置和评价指标。
  - [x] 基线、比较和相对优势。
  - [x] 证据不足、过强全称断言和分布偏移问题。
  - [x] 需要确认计划上下文的问题，验证 `[Pn]` 与论文 `[En]` 的边界。
- [x] B-02-02 每个问题只从本地已持久化的 completed assistant message 导出；不从回答文本反推 Gold。
- [x] B-02-03 导出时默认匿名化：`message_id=null`，不带 request id，不带数据库内部路径。
- [x] B-02-04 人工填写 `human_verdict`：`supported`、`insufficient_evidence` 或 `unsupported`；未确认前保留 `null`。
- [x] B-02-05 对 `supported` 题逐篇确认必需论文；对 `insufficient_evidence` 题不预置必需论文。
- [x] B-02-06 v1/v2 均已完成第二位人工复核；用户确认后创建 `gold` 副本，draft 原文件保留，不因机械指标为 `1.0` 自动冻结。
- [x] B-02-07 v2 的 5 条新样本均有 `retrieval_audit`；v1 的 2 条历史消息审计为空，已明确标记为“无运行时审计”，未补写。

v3 新增真实样本报告为 `evaluation/chat/reports/gnn_explanations_v3_report.json`：2/2 观测、2/2 `succeeded`、2/2 reranker `applied`、人工 verdict 覆盖率 `1.0`、人工一致率 `1.0`。v3 保持 `draft`，候选必需论文已列出但未升级为 Gold。

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
- [x] 离线 runner 将额外 query 数量限制在规划器上限内，并记录额外 embedding、Milvus、reranker 调用和延迟；生产 Chat 仍未接入。
- [x] section hint 只使用现有 canonical section，例如 `Method`、`Experiment`、`Related Work`；不得把 hint 当作论文事实。

#### B-04-2 候选合并

- [x] 只在 workspace 过滤生效的召回层执行 facet query。
- [x] 合并前按 `chunk_id` 去重；合并后继续按论文保留最高分 chunk。
- [x] primary 和 facet 结果的来源、chunk offset、paper id 必须完整保留；报告只保存 provenance/offset，不复制 chunk 正文。
- [x] primary 失败时仍 fail closed；facet 单独失败时不得伪造成功，应记录 failed/degraded 诊断。
- [x] 记录 facet 类型、query 数、各 query 召回数和合并后论文数，供 A/B 报告使用。
- [x] 不通过任意未经评测的分数阈值删除论文证据。

#### B-04-3 离线 A/B 验收

- [x] 新增只读实验 runner `evaluation/retrieval/run_chat_facet_ab.py`，明确标记 `production_enabled=false`、`llm_called=false`、`workspace_mutated=false`。
- [x] 在固定 retrieval Gold Set 上跑 primary-only 与 primary+facet 两组结果；`minimal_gnn_v1` 的 3 条 semantic query 均成功、无未解析论文，workspace leakage 两组均为 `0.0`，但没有任何问题触发当前 facet 规则，因此报告标记为 `experiment_usable=false`，不能把相同结果当作 facet 收益。
- [x] 在 Chat QA draft 上比较必需论文覆盖、独立论文数、回答中有效引用覆盖和人工证据不足判断；本轮使用 5 条带审计真实样本。
- [x] 检查 workspace leakage 必须为 `0`；固定 Gold 报告 primary/faceted 最大 leakage 均为 `0.0`，Chat QA facet A/B 当前未接入生产合并链路。
- [x] 记录额外延迟、reranker 降级率和空结果变化；本轮 5/5 检索成功、5/5 reranker `applied`。
- [x] 只有在覆盖提升或明确解决已人工确认的缺口，且无安全/隔离回归时，才提出启用方案；本轮未满足，因此不提出启用。
- [x] 没有稳定收益，保留 planner 作为实验工具，不接入默认 Chat。

本轮 A/B 实验报告为 `evaluation/retrieval/reports/chat_gnn_facet_ab_draft_unsandboxed.json`。embedding、Milvus 和 reranker 恢复后，primary-only 的必需论文平均覆盖为 `1.0`，primary+facet 为 `0.875`；5 个问题中 facet 提升 `0` 条、回归 `1` 条。回归发生在 `chat-gnn-03`：方法 facet 将必需的 `Self-Interpretable Graph Learning with Sufficient and Necessary Explanations` 排出 top-k，覆盖从 `1.0` 降至 `0.5`；四个带 facet 问题平均增加约 `794.15 ms`。因此当前结论是保持 facet 默认关闭，不能据此接入生产 Chat，也不能把方法 facet 宣称为质量提升。

固定 Retrieval Gold 的补充报告为 `evaluation/retrieval/reports/minimal_gnn_facet_ab_draft.json`。`minimal_gnn_v1` 的 3 条 semantic query primary-only 平均 Recall@10 为 `1.0`、MRR@10 为 `0.8333`；由于 0 条 query 命中 facet 规则，primary+facet 实际上等价于 primary-only，报告的 `experiment_usable=false`。这次运行只证明固定 Gold 的 workspace 隔离和基线可达，不足以证明 facet 的质量收益；不得为制造 facet 覆盖而修改固定 Gold，后续若要补固定基准，应新增经人工确认的问题集或使用独立的产品相关 draft 集。

此前的受限网络运行曾将 5 个 primary query 分型为 `embedding_unavailable`；该结果保留在本地失败报告中，但不作为质量结论。后续 A/B 必须优先确认 embedding 可达，再比较检索结果。

### B-05. 章节优先级

- [x] 先统计真实语料中 `Method`、`Experiment`、`Related Work` 等 canonical section 的可用比例。
- [x] 不对缺少章节标记的 chunk 做硬过滤；只能作为查询 hint、排序特征或诊断信息。
- [x] 公式/损失问题优先观察 `Method` 和 `Related Work`，但不能丢弃真实命中的其他章节。
- [x] 数据集/实验/基线问题优先观察 `Experiment`，同时保留 `Method` 或 `Related Work` 中的定义证据。
- [x] 章节优先级与每论文去重、workspace filter、NUL 防护和来源护照测试一起验收。
- [x] 章节 hint 导致必需论文召回下降时默认关闭；本轮 section hint 保持诊断-only。

当前 workspace 的只读报告为 `evaluation/retrieval/reports/section_coverage_local.json`，基于 24 篇 active paper 的 current chunk-index artifact，共 834 个 chunk：`Method=34`、`Experiment=14`、`Related Work=10`，`Unknown=728`；仅 2 篇论文含 Method，3 篇含 Experiment，3 篇含 Related Work，19 篇含 Unknown。因此不能把章节 hint 作为硬过滤或未经验证的排序门。

### B-06. 阈值校准与 Gold 冻结

- [x] 先区分三个概念：检索相关性阈值、证据覆盖阈值、回答“证据不足”判断。
- [x] 不把 reranker 分数直接当作证据覆盖，也不把 `confidence` 当作 Evidence Passport。
- [x] 汇总固定 retrieval Gold、Chat QA draft 和真实审计样本后，形成候选观察；不自动写入生产阈值。
- [x] 对当前唯一可观测候选规则记录 false positive/false negative：报告 `evaluation/chat/reports/gnn_explanations_threshold_calibration.json` 在 9 条人工样本上将 `mechanical_passed` 作为“supported”代理时记录 FP=`2`（`chat-gnn-02`、`chat-gnn-07`）、FN=`0`；该规则明确不是数值生产阈值。
- [x] 由用户确认“不批准生产数值阈值；k=15 仅作诊断观察点；`insufficient_evidence` 必须人工确认”；自动 runner 只计算，不自动批准。
- [x] Chat QA v1/v2 Gold 已完成双人复核、版本号以及 corpus/chunk/embedding/reranker freeze 信息；固定 Retrieval Gold 未修改。
- [x] Gold 冻结后，产品相关 draft 可以继续新增，但不得回写或修改固定 Gold。
- [x] 阈值接入代码前已由现有边界测试覆盖：无命中/单篇与多篇覆盖、workspace leakage、reranker degraded、跨 workspace 来源和引用缺失；当前没有生产阈值接入代码。

固定 Retrieval Gold smoke baseline 报告为 `evaluation/retrieval/reports/minimal_gnn_gate_baseline.json`：semantic_search Recall@10=`1.0`、similar_work=`0.6667`、counter_evidence=`1.0`，三类 workspace leakage 均为 `0.0`，Gate overall=`FAIL`。similar_work 的缺口是 `min-sw-01` 和 `min-sw-02` 各命中 1/2 个 Gold 论文，`min-sw-03` 命中但首个 Gold 排在第 8 位；这说明当前 paper-level 相似工作存在待人工确认的召回缺口，不是调整阈值即可修复，也不足以单凭一次 smoke 启动混合检索。该报告使用 `--minimal` 跳过 judge，只作为召回链路基线，不作为角色事实结论。

为区分候选召回与 top-k 截断，已对同一 workspace、同一固定 Gold 以 `top-k=20` 复跑，报告为 `evaluation/retrieval/reports/minimal_gnn_gate_baseline_top20.json`：semantic_search、similar_work、counter_evidence 的 Recall@20 均为 `1.0`，workspace leakage 均为 `0.0`；similar_work 的 Gold 论文在 `min-sw-01` 排名第 `4/15`、`min-sw-02` 排名第 `7/12`、`min-sw-03` 排名第 `7`。因此在这组样本中，top-k=10 的 similar_work 缺口表现为排序/截断问题，尚不足以证明 dense candidate recall 稳定缺失，也不能据此启动 C-01 混合检索或修改固定 Gold。后续阈值评估仍需由人工同时确认 top-k、论文级去重、引用覆盖和延迟之间的取舍；两份报告均使用 `--minimal`，不作为 counter-evidence 角色事实结论。

随后补齐 `top-k=5/15` 曲线，报告分别为 `evaluation/retrieval/reports/minimal_gnn_gate_baseline_top5.json` 和 `evaluation/retrieval/reports/minimal_gnn_gate_baseline_top15.json`；四个 k 值的结果为：k=5 时 similar_work=`0.1667`、counter_evidence=`0.5`；k=10 时 similar_work=`0.6667`；k=15 和 k=20 时三类 Recall 均为 `1.0`。本轮同时修正了评测器固定输出 `@10` 标签的问题，使报告键与实际 `top_k` 一致，并以单元测试覆盖动态指标键。k=15 只能作为本固定 corpus 的候选观察点，不能直接写入生产配置；完整后端回归为 `469 passed, 2 warnings`。

已按候选 k=15 运行一次完整 Gate（启用 reranker 和 counter-evidence judge），报告为 `evaluation/retrieval/reports/minimal_gnn_gate_full_top15.json`：semantic_search Recall@15=`1.0`、counter_evidence Recall@15=`1.0`，similar_work Recall@15 降为 `0.6667`，整体 Gate=`FAIL`；三类 workspace leakage 均为 `0.0`，无 unresolved paper ref，judge 两条 query 均成功。similar_work 的 Gold 排名为 `min-sw-01=10/1`、`min-sw-02=14/4`、`min-sw-03=miss`。因此此前 minimal 曲线的 k=15 通过只说明关闭 reranker 时候选可达，不能作为真实 Chat/检索链路的阈值依据；当前更准确的诊断是 reranker 排序后在 top-k 截断处丢失 Gold。counter-evidence 两条 role diagnostic 均为 `0.5`，仅作角色排序诊断，不覆盖 paper-level Gate 结论。k=20 完整 Gate 未运行，避免未经单独授权扩大送入 judge 的 passages；本地封版不修改生产阈值、不启动 C-01。

### B-07. 生成可靠性回归

- [x] 同步/流式 `disable_thinking=True` 已覆盖。
- [x] 论文、计划、报告、代码草案来源边界已落地。
- [x] 引用一致性质量门和失败回退已落地。
- [x] 增加同步/流式成对回归样本：同步和流式无论文命中均保持 `no_evidence`、不调用 LLM，且已有同步/流式论文引用门禁样本覆盖来源边界。
- [x] 增加“已检索但无引用”“失效 `[En]`”“失效 `[Pn]/[Dn]/[Cn]`”“无论文命中”“reranker degraded”样本；其中来源标记纯函数、离线 QA 和 API 同步/流式样本分别验证边界。
- [x] 验证修复调用仍是一次上限，且修复调用同样 `disable_thinking=True`、不传 `reasoning_effort`。
- [x] 验证失败回退不会写入不存在的 citation/evidence，不覆盖原始检索结果；同步和流式失败修复均落到确定性证据不足文本。
- [x] 记录首 token、完成延迟、prompt 字符数、输出 token 和质量门状态；敏感内容不进入报告。新增 migration `0024_chat_generation_observability`、API 字段和只读聚合器 `evaluation/chat/report_generation_observability.py`。
- [x] 生成侧指标必须和人工事实判断分开；离线报告将机械引用/来源检查、检索审计和人工 `human_verdict` 分栏，不能用结构性引用通过代替事实正确。

本轮 B-07 结构回归继续覆盖同步检索失败、同步/流式无论文命中、重排降级和流式引用修复失败回退样本；`generation_observability_local.json` 当前统计 49 条 assistant 消息（38 条 completed），其中 2 条新消息真实写入了四类运行时字段：首 token 延迟 P50=`1023.02 ms`、完成延迟 P50=`9466.98 ms`、prompt 字符 P50=`15937.5`、response 字符 P50=`2305.5`。其余历史行缺失是迁移前真实状态，不回填。

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

- [x] 运行相关测试：Chat API、Chat QA、facet、生成观测和阈值诊断定向测试均通过。

```powershell
cd D:\MyCode\Spark-competition\refactor\GapMind\backend
.venv\Scripts\python.exe -m pytest tests\test_chat_api.py tests\test_chat_qa_evaluation.py -q
```

- [x] 运行完整后端测试：`469 passed, 2 warnings`。

```powershell
.venv\Scripts\python.exe -m pytest tests\ -q
```

- [x] 如果改了 migration，已升级并检查本地数据库：当前 `0024_chat_generation_observability (head)`。

```powershell
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\alembic.exe current
```

- [x] 检查 `git diff --check`。
- [x] 检查受保护路径未出现在 staged diff。
- [x] 已汇报测试和剩余风险，当前保持未 commit，等待用户明确 commit。

### 7.2 涉及 API/schema 的改动

- [x] 重新生成 OpenAPI 类型：已运行 `npm run gen:api`，`api.gen.ts` 由工具生成。

```powershell
cd D:\MyCode\Spark-competition\refactor\GapMind\frontend
npm run gen:api
```

- [x] 运行完整前端检查：56 tests、typecheck、lint（0 errors/14 warnings）和 Vite production build 均通过；为保护 `tsconfig.node.tsbuildinfo`，构建使用 `tsc --noEmit` + `npx vite build`。

```powershell
npm run test -- --run
npm run typecheck
npm run lint
npm run build
```

- [x] 不手写 `frontend/src/api/types/api.gen.ts`。
- [x] 前端检查产生的 `frontend/vite.config.js`、`frontend/tsconfig.node.tsbuildinfo` 未被修改或暂存。

### 7.3 真实本地 Chat 观测

- [x] 确认后端已加载最新 migration 和代码，Alembic 当前为 `0024_chat_generation_observability (head)`。
- [x] 在 Demo workspace 发送两条新问题，均已等待 assistant completed。
- [x] 只读读取 Chat detail，确认 `retrieval_audit`、citations、source manifest 和 grounding 状态。
- [x] 用导出器生成匿名快照；默认不带 `message_id`。
- [x] 人工确认后将用户提供的两个 `human_verdict=supported` 仅写入评测副本；workspace 消息保持不变。
- [x] 不修改 workspace 论文、消息、Gold 或固定评测结果来修复输入。

## 8. 本地封版 DoD

RAG/生成优化达到本地封版条件，需要同时满足：

- [x] 阶段 A 全部测试仍通过。
- [x] 阶段 B 的 citation quality gate、Chat QA、retrieval audit 和生成回归均有可重复报告。
- [x] Chat QA 至少覆盖支持、证据不足、失效引用、计划/报告/代码来源边界和 reranker degraded。
- [x] 新增样本的审计覆盖率达到当前人工复核范围；旧消息缺少审计时已明确标注。
- [x] 确定性分面检索保持关闭，并保留 primary-only 对照、检索指标、延迟、隔离和人工复核结果。
- [x] 没有未经评测的相关性阈值、证据不足阈值或自动事实判断。
- [x] 不把 draft Gold、机械 `mechanical_passed` 或 citation validity 等同于事实正确率。
- [x] 阶段 C/D 的延期状态和启动条件已记录。
- [x] 完整后端测试通过；前端测试、类型检查、lint、build 全部通过。
- [x] 所有改动保持待用户审查后再提交；本轮没有部署和 push。

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
