# GapMind 完整功能任务清单（功能层）

> 更新日期：2026-08-04
> 依据：`mvp_core_spec.md` + `mvp_acceptance_and_sequence.md` + `discover_agent_product_and_implementation_plan.md`
> 状态图例：✅ 已完成 / ⏳ 进行中 / 🔲 未开始
> 本文件只描述"系统能做什么"，不涉及具体技术实现。

---

## Stage 0 — 产品设计与语料冻结 ✅

| 功能 | 状态 |
|---|---|
| MVP 核心闭环规格（边界、对象语义、HITL 状态机） | ✅ `mvp_core_spec.md` |
| 跨模块数据契约 v1 | ✅ `data_contracts_v1.md` |
| 主 Demo Case（Self-Interpretable GNN + OOD） | ✅ `demo_case_self_interpretable_gnn.md` |
| 12 篇受控 Smoke Corpus 外部 ID 核对 | ⏳ 3 篇已核对，9 篇待核对 |

## Stage 1 — 知识抽取与证据基础 ✅（Phase 3 Smoke 已过）

| 功能 | 状态 |
|---|---|
| 论文上传（手动 + 元数据 + 外部导入） | ✅ |
| PDF 解析 → 纯文本 / 结构化 Markdown / 分块 | ✅ |
| 知识抽取（方法 / 任务 / 数据集 / 主张 / 局限） | ✅ |
| 跨论文规范实体合并（同一方法只存一份） | ✅ |
| 论文级陈述（Claim）+ 证据回链（EvidenceSpan） | ✅ |
| 抽取失败审计（rejection 记录、幂等重试） | ✅ |
| **抽取质量人工审查**（抽查 5 个 item/篇，核对证据忠实度） | ✅ **RG-1**（回链 100% + 发现去重问题，P0 已修） |

## Stage 2 — Workspace 检索 🔲（技术链路通 + minimal Gate 过，完整 Gate 待语料扩充）

| 功能 | 状态 |
|---|---|
| 论文级向量索引 + 跨工作空间隔离 | ✅ |
| 语义检索（自然语言查论文） | ✅ |
| 相似工作（输入一篇论文，找相关论文） | ✅ **RG-4**（论文级聚合 + 多样性） |
| 反证检索（输入主张，找反驳/限定证据） | ✅ **RG-5**（角色排序 + empty_reason 三态） |
| 来源论文排除（检索反证时不返回主张来源） | ✅ **RG-2** |
| 检索评测框架 + Gold Set（Recall@10 指标） | ✅ **RG-3** |
| 索引生命周期验证（重复索引/删除/软删除/降级） | ✅ **RG-6** |
| 反证专项验证（三类主张 × 5 条人工标注） | ✅ **RG-7** |
| **minimal gold set Gate**（9 篇语料完整版） | ✅ **RG-8 部分**（2026-08-06：recall 1.0/1.0/1.0 + leakage 0 全 PASS） |
| **完整 demo Gate**（12+ 篇 corpus） | 🟡 semantic 1.0 ✅；similar 0.778 / counter 0.667 ❌（差 <0.03，需调召回）；详细见 `docs/retrieval_gate_report.md` |
| 检索结果人工标注 + Gold Set 定稿 | ⏳ **RG-1**（人工审查的一部分） |

## Stage 3 — 外部新颖性核验 ⏳（管线 PASS，query 生成待增强）

| 功能 | 状态 |
|---|---|
| 从工作空间线索构造外部检索问题 | ⏳ 研究轴 query 库 + 精确名查找已落地（LLM 轴分解 + 方法名 grounding + `_title_verified` 标题验证前置），auto recall 0.0→0.286、MRR 0.5（GIB/IRM top-3、候选主题相关）；剩余 5 篇 gold 需 LLM 恰好生成概念词（非确定性）|
| Semantic Scholar 召回外部论文元数据 + 摘要 | ✅ |
| 外部候选角色判别（相似/重叠/限定/反驳/未知） | ✅（heuristic 打底 + LLM 批量精化，8/batch，失败保留启发式） |
| 高价值开放 PDF 全文下载 + 解析核验 | ⏳ 导入链路已建（import_selected_candidates），全文核验流程待跑通验证 |
| 外部结果快照保存（元数据 vs 全文明确区分） | ✅（snapshot_payload + evidence_level 两态） |
| 外部检索失败时 Opportunity 标记"核验不完整" | ✅（verification_status = failed / incomplete） |
| **Stage 3 Gate 验证**（主 Case gold 外部反证 Top 10 召回） | 🟡 **管线 PASS（curated 0.857）；auto 经轴 query 库 + 精确名查找后 0.286 recall / MRR 0.5（GIB/IRM top-3、候选主题相关）**；详见 `docs/external_novelty_gate_report.md` |

## Stage 4 — 研究机会 Proposal 🔲（同步原型有，正式闭环未过）

| 功能 | 状态 |
|---|---|
| 完整 Opportunity 数据模型（17 字段 + 版本 + 证据 + 决策） | ✅（代码已建，未验收） |
| 研究机会生成（输入主题/主张 → 多候选机会） | ⏳ 有同步单候选原型，缺异步 Run + 多候选 |
| 硬门槛校验（至少 2 篇独立全文证据） | ✅（代码已建） |
| 证据不足时的自主收窄/重试（Agent 式编排） | 🔲 |
| 生成过程审计（Prompt/模型/语料/检索快照版本） | ⏳ 部分 |
| 机会生成质量验收（5 个 Case、Unsupported ≤20%） | 🔲 |

## Stage 5 — 人机协同决策与验证计划 ⏳（代码大部分已建，Gate 未过）

| 功能 | 状态 |
|---|---|
| 用户决策：确认 / 编辑确认 / 拒绝 / 延后 | ✅（代码已建） |
| 机会版本不可变 + 新旧版本 diff | ✅ |
| 决策审计（HumanDecision + 时间线） | ✅ |
| 已确认机会 → 可编辑研究计划 | ✅ |
| 研究计划结构（问题/假设/验证步骤/证伪标准） | ✅ |
| 前端机会工作台 + 证据原文阅读路径 | ⏳ 部分 |
| HITL 验收（4 种决策 × API/UI/测试 + Timeline 追溯） | 🔲 |

## Stage 6 — 比赛 Demo 与评测封版 🔲

| 功能 | 状态 |
|---|---|
| 冻结所有版本（语料/标注/Prompt/模型/解析器/Schema） | 🔲 |
| 正常路径 + 外部 API/LLM 失败降级路径演练 | 🔲 |
| 3 次全新数据库端到端演练 | 🔲 |
| 记录解析/抽取/检索/发现的耗时、错误率、token 成本 | 🔲 |
| 演示"系统主动收窄/否定的弱机会" | 🔲 |
| 演示"用户编辑确认 → 计划"完整路径 | 🔲 |
| 所有关键结论 UI 回链论文原文 | 🔲 |

## 暂停范围（Stage 6 通过后才排期）

| 功能 | 说明 |
|---|---|
| 实验自动执行 / 结果分析 / 论文写作 / 审稿回复 | Execute→Analyze→Publish→Respond |
| 抽取模型微调（zf 并行研究，不阻塞闭环） | |
| GNN 排序（无监督信号，明确不做） | |
| 多用户认证 / 协作 / 每日推荐 | 赛后 |

---

## 当前焦点：阻塞在 Stage 2

整个系统的**唯一硬阻塞**是 Stage 2 检索质量 Gate——它卡住 Stage 3（外部核验，依赖高质量
Workspace 线索）和 Stage 4（正式机会生成，被 `mvp_acceptance_and_sequence.md` 明确禁止在
Gate 前进行）。

未完成的 RG（按依赖顺序）：

```
RG-1  抽取质量人工审查（也产出检索 Gold Set 标注）  ← 可并行
RG-4  Similar Work 论文级聚合 + 多样性           ← 依赖 RG-3（已完）
RG-5  反证角色排序 + Judge 角色约束              ← 依赖 RG-3（已完）
RG-6  索引生命周期测试                            ← 独立
RG-7  反证专项验证                                ← 依赖 RG-5
RG-8  跑检索质量 Gate（四指标全过才 GO）          ← 依赖 4/5/6/7
RG-9  文档收尾 + 状态同步                         ← 依赖 RG-8
```

检索质量 Gate 判据（`mvp_acceptance_and_sequence.md` Stage 2）：

- Semantic Search Recall@10 ≥ 0.80
- Similar Work Recall@10 ≥ 0.80
- Counter-Evidence Recall@10 ≥ 0.70
- workspace 泄漏 = 0
- 所有结果可回链 Paper + artifact

---

## 状态更新记录

| 日期 | 内容 |
|---|---|
| 2026-08-04 | 初版；RG-2（来源排除）、RG-3（评测框架）已完成 |
| 2026-08-06 | Stage 3 外部检索多 query 构造 + 轮转合并；**Stage 3 Gate 首跑：管线 PASS（curated 0.857）、query 自动生成 FAIL（auto 0.0）**；详见 `docs/external_novelty_gate_report.md` |
