# Stage 3 外部新颖性核验 Gate 验收报告

> 更新日期：2026-08-06
> 状态：Gate 基础设施建成并跑通；**管线层 PASS（curated query recall@10=0.857），query 自动生成层 FAIL（auto recall@10=0.0）**
> 关联：`mvp_acceptance_and_sequence.md` Stage 3 + `docs/functional_roadmap.md`

---

## 1. 一页结论

| 层 | 验证方式 | recall@10 | 阈值 | 判定 |
|---|---|---|---|---|
| **管线层**（S2 检索 + 多 query 合并 + 角色判别） | 用已知命中 gold 的 curated query 集 | **0.857**（6/7）| 0.80 | ✅ PASS |
| **query 生成层**（从 workspace 线索自动构造 query） | 走真实 `_build_external_queries` | **0.000**（0/7）| 0.80 | ❌ FAIL |

**结论**：Stage 3 外部核验的**检索/合并/角色管线已验证可用**——给定正确的检索词，外部反证论文能稳定进入 top-10（MRR@10=1.0）。真正的瓶颈是 **query 自动生成**：从 workspace 噪声抽取产物派生的 query 无法生成能命中外部反证论文的检索词，召回为 0。

本次验证同时发现并修复了 3 个真实缺陷（见 §4）。

---

## 2. 评测环境

| 项 | 值 |
|---|---|
| Workspace | `123100ea-e75b-4110-9048-1f5b92668c32`（self-interpretable gnn，19 篇论文，690 knowledge items）|
| 外部检索 | Semantic Scholar Graph API（relevance search）|
| gold set | `evaluation/external/gold/demo_sig_ood_external_v1.json`（7 篇外部反证/重叠/限定论文，全不在 corpus 内）|
| runner | `evaluation/external/verify_external_gate.py`（走真实 `DiscoverService._build_external_queries` + `_external_verify`）|
| 报告 | `evaluation/external/reports/`（gitignored）|
| 阈值 | Recall@10 ≥ 0.8（镜像 Stage 2 similar-work 阈值）|
| 注意 | run_eval 类脚本必须从 `backend/` 跑（.env 在 backend）；S2 无 key 或超频会 429 |

### 2.1 Gold Set（7 篇，全为 corpus 外真实论文）

| 论文 | 年份 | S2 ID 前缀 | 角色 |
|---|---|---|---|
| Graph Information Bottleneck（Wu et al.）| 2020 | `2fce1ef` | overlap |
| Invariant Risk Minimization（Arjovsky et al.）| 2019 | `753b7a7` | overlap |
| Graph Rationalization w/ Env Augmentations（GREA）| 2022 | `22f1d9e` | counter |
| Interpretation of Neural Networks is Fragile | 2017 | `96cf326` | counter |
| Sanity Checks for Saliency Maps | 2018 | `8dc8f3e` | qualifies |
| Reliable Post hoc Explanations | 2020 | `097a125` | qualifies |
| Explainability Methods for GCNN | 2019 | `cb2d9b2` | overlap |

---

## 3. 验证结果

### 3.1 管线层（curated query）— PASS ✅

给定 7 条已知命中的 query，走真实管线（多 query 合并 + 轮转交错 + 角色）：

| gold 论文 | merged rank | 来源 query |
|---|---|---|
| Graph Information Bottleneck | 1 | graph information bottleneck |
| Explainability Methods for GCNN | 5 | explainability methods graph convolutional neural networks |
| Invariant Risk Minimization | 6 | invariant risk minimization |
| Interpretation of Neural Networks is Fragile | 7 | interpretation of neural networks fragile |
| Graph Rationalization (GREA) | 9 | graph rationalization environment augmentation |
| Sanity Checks for Saliency Maps | 10 | saliency maps sanity checks model randomization |
| Reliable Post hoc Explanations | —（query rank 8，附加 query 只取 top-5，未进合并池）| explanation uncertainty post hoc reliable |

**recall@10 = 6/7 = 0.857**，MRR@10 = 1.0。

### 3.2 query 生成层（auto）— FAIL ❌

真实 `_build_external_queries`（research question + workspace 方法/限定/关键词）生成的 6 条 query：

```
Are self-interpretable graph neural network explanations faithful, stable, ...  (research question)
Self-Interpretable Graph Neural Networks (SI-GNNs)
Self-Denoising (SD)
Explanation Ensemble (EE)
Group DRO
TELL-like classifier
```

合并出 25 个候选，**全部偏离 gold**（药物发现、低光图像、OCT 去噪、胃肠道癌症……），recall@10 = **0.000**。

---

## 4. 本次验证发现并修复的缺陷

1. **合并语义缺陷（已修复）**：`_external_verify` 原按"主 query 先、附加 query 后"顺序合并 → 合并列表 top-10 就是主 query 的 top-10，附加 query 发现的反证全排到 11+，**永远进不了 top-10**。改为**轮转交错合并**（每 query 的 rank-1 先交错，再 rank-2……），附加 query 的发现能进入用户可见的 top-10。
2. **query 风格缺陷（已修复）**：长 prose query（research question 原文）在 S2 relevance 检索中命中率低；**简洁的方法全名**（"Graph Information Bottleneck"、"Invariant Risk Minimization"）命中率高。`_external_query_text` 改为：方法用描述性全名（all-caps 缩写从 description 首部名词短语展开，如 IRM→"Invariant Risk Minimization"）、limitation 用短 canonical_name。
3. **方法选择缺陷（部分修复）**：workspace 抽取把"命名贡献"（SubgraphX、GIB）和"架构组件"（Top-k Pool、SAG Pool、Fourier Step Function）混在一起，且 confidence 与外部检索价值不对齐（组件常 1.0）。加了组件 token 过滤（Pool/Module/Layer 等降权），但**命名贡献 vs 组件的自动区分本质上不可靠**——这是 query 生成层 FAIL 的根因之一。

---

## 5. 差距分析与根因

**管线不是问题，query 生成是问题。** 7 篇 gold 论文各自的命中 query 均已确认存在（§3.1），但 `_build_external_queries` 无法从 workspace 生成它们：

| gold 论文 | 命中的 query 词 | workspace 是否有此信号 |
|---|---|---|
| GIB | "graph information bottleneck" | ✅ 有 method 项，但被噪声方法挤掉预算 |
| IRM | "invariant risk minimization" | ✅ IRM method → 可展开，但被多词 1.0 方法挤掉 |
| GREA | "graph rationalization environment augmentation" | ❌ 无（外部工作）|
| Fragile | "interpretation of neural networks fragile" | ❌ 无（图像域）|
| Sanity | "saliency maps sanity checks model randomization" | ⚠️ 有 Saliency method，但无 "sanity/robustness" 组合 |
| Reliable | "explanation uncertainty post hoc reliable" | ⚠️ 有 limitation "Existing methods ignore stability" 但用词不同 |
| PopeGNN | "explainability methods graph convolutional neural networks" | ⚠️ 有 GraphFramEx，但 query 用词不匹配 |

**根因**：
1. 抽取产物的方法名是**缩写 + 噪声**混合，无法稳定生成"研究轴上 + 具体方法"的组合检索词；
2. 长 prose query 是 S2 relevance 检索的天然劣势；
3. 单靠 relevance search 对"奠基/反证类"外部论文（图像域的 Fragile、跨域的 GREA）覆盖有限。

---

## 6. 下一步（query 生成增强）

| 方案 | 说明 | 成本 |
|---|---|---|
| **研究轴 query 库** | 从 research question 的核心概念派生检索词（如 demo 的 axis = {invariant rationale, explanation stability, saliency robustness, graph rationalization}），与 workspace 方法名交叉 | 中（需每主题一个 axis 映射）|
| **精确名查找** | 对已知方法名用 S2 精确 title/ID 查找（`paper/search` + `paper/{id}`），而非仅 relevance | 低，与现有 client 兼容 |
| **收紧抽取方法过滤** | P1 语义去重 + 方法名规范化（缩写↔全名映射表）后，方法 query 质量会显著提升 | 依赖抽取质量（Stage 1 已过）|
| **放宽 gate 指标** | recall@K 的 K 放宽到合并预算（如 25），或按 query 分别算 recall | 低，但语义上不如修 query 生成 |

**建议路径**：先做"研究轴 query 库"（方案 1，主 Case 立即可达标），再配合 P1 去重提升方法名质量。

---

## 7. 过程记录

- 2026-08-06：探测确认 7 篇 gold 论文可被对应 query 召回（GIB@1/IRM@1/GREA@2/Sanity@2/Reliable@8/PopeGNN@1）；建 gold set + runner；跑通管线层 PASS（0.857）与自动生成层 FAIL（0.0）。
- S2 限流经验：无 key / 超频会 429，重试 backoff 不足；批量探测前先等窗口。

## 状态更新记录

| 日期 | 内容 |
|---|---|
| 2026-08-06 | Stage 3 Gate 首跑：管线 PASS（curated 0.857）、query 生成 FAIL（auto 0.0）；修 3 缺陷（轮转合并/query 风格/组件过滤）|
