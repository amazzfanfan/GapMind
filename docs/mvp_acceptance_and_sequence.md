# GapMind MVP 验收门槛与实施顺序

> 版本：v1
> 更新日期：2026-07-25
> 目标：以可演示、可评测的核心闭环替代按功能数量推进。

每个阶段都必须通过 Gate 才进入下一阶段。未通过时只修复当前阶段，不并行扩展赛后功能。

## Stage 0：设计与语料冻结

交付物：

- [`mvp_core_spec.md`](mvp_core_spec.md)
- [`data_contracts_v1.md`](data_contracts_v1.md)
- [`demo_case_self_interpretable_gnn.md`](demo_case_self_interpretable_gnn.md)
- [`phase3_baseline_audit.md`](phase3_baseline_audit.md)

Gate：

- 团队确认 Workspace/外部检索边界；
- 确认 CanonicalEntity、PaperMention、Claim、EvidenceSpan 的职责；
- 12 篇 Smoke Corpus 完成外部 ID 和版本核对；
- 主 Demo Case 的 overlap/counter-evidence 至少有一项人工 gold 标注；
- 跨模块 fixture 的 schema version 固定为 1.0.0。

## Stage 1：修正 Knowledge 与 Evidence 基础

实施内容：

1. Migration A：CanonicalEntity、paper-scoped knowledge、ExtractionRun 和幂等键；
2. chunk 统一引用 parsed_text artifact；
3. EvidenceSpan 统一引用 parsed_markdown artifact；
4. extraction trigger/retry 与可观察状态；
5. 原子事务、严格 schema 和 evidence offset 校验；
6. 章节批处理替代 40,000 字符静默截断。

Gate：

- 合法抽取能原子写入；
- 任一 item/关系非法时零部分数据落库，Task 最终为 failed；
- 同一 run 连续执行两次，业务行数和内容不变；
- 两篇论文提及同一方法时只有一个 CanonicalEntity、两个独立 Mention；
- Smoke Set 关键 EvidenceSpan 的 artifact 切片匹配率为 100%；
- 论文 Introduction、Experiment、Discussion/Conclusion 均有批次覆盖记录；
- 所有 Phase 3 单元和端到端测试通过。

## Stage 2：Workspace Retrieval

实施内容：

1. Milvus collection 与版本化 embedding metadata；
2. `semantic_search`；
3. paper-level `similar_work`；
4. counter-evidence 两阶段流程：候选召回 → 语义判别；
5. workspace filter、结构化失败和 contract tests。

评测集：主 Demo Case + 四个轻量 Case。每个 query 预先标注关键 paper/chunk。

Gate：

- Workspace 数据无跨空间泄露；
- Semantic Search Recall@10 不低于 0.80；
- Similar Work Recall@10 不低于 0.80；
- Counter-Evidence Recall@10 不低于 0.70；
- 检索失败返回 `failed/degraded`，不返回伪成功空结果；
- 所有结果可回链到 Paper 和 source artifact；
- 基准配置、embedding 版本和 corpus version 可复现。

以上阈值是 Smoke/Development Set 的起始门槛，不宣称通用领域性能。

## Stage 3：外部新颖性核验

实施内容：

1. 从 Workspace 线索构造外部检索 query；
2. Semantic Scholar 元数据/摘要候选召回；
3. 候选角色判别：similar、overlap、qualify、contradict、unknown；
4. 只对高价值开放 PDF 进入全文解析；
5. 保存 Discover Run 的外部结果快照和版本。

Gate：

- 每个 Opportunity 生成前至少执行一次外部检索；
- 主 Case 的 gold overlap/counter-evidence 能被 Top 10 召回；
- metadata-only 与 full-text evidence 在 UI/API 中明确区分；
- 摘要不能成为关键结论的唯一证据；
- 外部 API 失败时 Opportunity 明确标为 verification incomplete。

## Stage 4：Opportunity Proposal

实施内容：

1. Migration B 的 Opportunity/Version/Evidence；
2. Discover Agent 编排结构化知识、本地检索和外部核验；
3. 硬门槛校验和评分；
4. 生成过程记录 Prompt、模型、语料和检索快照版本。

单个 Opportunity Gate：

- 至少 2 篇独立论文的 full-text supporting evidence；
- 至少列出最相关 similar work；
- 展示 counter-evidence，或明确说明检索成功但未发现/检索失败；
- 解释为何已有工作不足，差异具体到 setting、metric、method 或 constraint；
- 不是单篇 Future Work/Limitation 的复述；
- 有 Research Question、可证伪 Hypothesis 和包含 falsification criteria 的 Validation Plan；
- 每项关键判断可以点击回到证据原文；
- 输出状态只能是 candidate。

系统 Gate：

- 五个 Opportunity Case 均能完成生成；
- Unsupported Opportunity Rate 不高于 20%；
- Missed Gold Similar Work Rate 不高于 20%；
- 至少两名团队评审者独立评分，保留分歧而非覆盖；
- 与 Vanilla RAG 至少完成一次盲评对比。

## Stage 5：HITL 与 Plan

实施内容：

1. confirm、edit_confirm、reject、defer；
2. Opportunity immutable version；
3. HumanDecision 与 Timeline；
4. confirmed Opportunity 转换为可编辑 ResearchPlan；
5. 前端 Opportunity 工作台和证据阅读路径。

Gate：

- 四种用户决策各有 API、UI 和回归测试；
- edit_confirm 保留旧版本和新版本 diff；
- rejected/deferred 不生成 Plan；
- Plan 永远引用确定的 Opportunity version；
- Timeline 能从生成、查看证据、用户决策追溯到 Plan；
- 页面清楚区分模型置信度、证据覆盖与用户确认状态；
- 主 Demo 可在一次连续操作中完成且不依赖数据库手工修改。

## Stage 6：比赛 Demo 与评测封版

Gate：

- 固定 corpus、annotation、prompt、model、embedding、parser 和 schema 版本；
- 准备正常路径以及外部 API/LLM 失败的降级路径；
- 完成至少 3 次全新数据库的端到端演练；
- 记录 PDF 解析、抽取、检索和 Discover 的耗时、错误率与 token 成本；
- 展示一个被系统主动收窄或否定的弱 Opportunity；
- 展示一个用户编辑后确认并转换为 Plan 的 Opportunity；
- 所有关键结果可从 UI 回链到论文原文。

## 当前开发顺序

严格按以下顺序实施：

```text
Migration A 设计与实现
→ Chunk/Evidence artifact 语义修复
→ Extraction schema、事务、幂等、分批与测试
→ Workspace Retrieval
→ External Verification
→ Migration B
→ Discover Agent
→ HITL
→ ResearchPlan
→ Opportunity Workbench
→ Benchmark + Demo hardening
```

## 明确暂停

在 Stage 6 之前暂停：

- Execute / Analyze / Publish / Respond；
- 自动运行 GitHub 仓库；
- Opportunity 微调；
- GNN 排序；
- 可编辑大型知识图谱；
- 每日论文推荐；
- 多用户认证和协作。

这些能力只有在核心闭环达到 Gate 后才能重新排期。
