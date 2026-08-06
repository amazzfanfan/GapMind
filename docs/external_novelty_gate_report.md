# Stage 3 外部新颖性核验 Gate 验收报告

> 更新日期：2026-08-06
> 状态：Gate 基础设施建成并跑通；**管线层 PASS（curated recall@10=0.857）；query 自动生成层经"研究轴 query 库 + 方法名 grounding + 精确名查找"增强后 0.0 → 0.286（recall）且 MRR 0.143 → 0.5（GIB/IRM 经精确查找前置到 top-3），候选主题相关；仍未达 0.8 阈值**
> 关联：`mvp_acceptance_and_sequence.md` Stage 3 + `docs/functional_roadmap.md`

---

## 1. 一页结论

| 层 | 验证方式 | recall@10 | MRR@10 | 阈值 | 判定 |
|---|---|---|---|---|---|
| **管线层**（S2 检索 + 多 query 合并 + 角色判别） | 用已知命中 gold 的 curated query 集 | **0.857**（6/7）| 1.0 | 0.80 | ✅ PASS |
| **query 生成层**（初版：workspace 派生 query） | 走真实 `_external_query_plan` | **0.000**（0/7）| 0.0 | 0.80 | ❌ FAIL |
| **query 生成层**（增强：LLM 轴 + grounding + 精确查找） | 走真实 `_external_query_plan`（real LLM）| **0.286**（2/7）| **0.5** | 0.80 | ❌ FAIL（改进显著）|

**结论**：Stage 3 外部核验的**检索/合并/角色管线已验证可用**——给定正确的检索词，外部反证论文能稳定进入 top-10（MRR@10=1.0）。query 自动生成经三层增强后：从召回 0、候选全是噪声 → **GIB/IRM 经精确名查找前置到 top-3（MRR 0.5）**、候选主题高度相关（含 GNN explanation benchmark、distribution-shift-in-explanations、invariant causal subgraph 等正是 demo 需要的反证/重叠工作）。精确指标 0.286 仍低于 0.8，原因是 gold set 中 5 篇特定奠基论文（GREA/Fragile/Sanity/Reliable/PopeGNN）需 LLM **恰好生成**其精确概念词——非确定性，这是 LLM 生成 + relevance 检索的固有边界。

本次验证同时发现并修复了 5 个真实缺陷（见 §4）。

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

### 3.2 query 生成层（初版 auto）— FAIL ❌

初版 `_build_external_queries`（research question + workspace 方法/限定/关键词）生成的 6 条 query：

```
Are self-interpretable graph neural network explanations faithful, stable, ...  (research question)
Self-Interpretable Graph Neural Networks (SI-GNNs)
Self-Denoising (SD)
Explanation Ensemble (EE)
Group DRO
TELL-like classifier
```

合并出 25 个候选，**全部偏离 gold**（药物发现、低光图像、OCT 去噪、胃肠道癌症……），recall@10 = **0.000**。

### 3.3 query 生成层（增强：研究轴 query 库 + 方法名 grounding）— 0.286 ❌（改进显著）

`_build_external_queries` 现用 LLM 将 research question 分解为 6 条轴 query（`_axis_queries_from_llm`，以 workspace 方法/局限为上下文），并把 LLM 提到的**方法全名**作为干净 query 补进预算（`_external_method_full_names` grounding）。真实 LLM + 12 条 query：

```
Are self-interpretable graph neural network explanations faithful, stable, ...  (research question)
self-interpretable graph neural network faithfulness
graph neural network explanation stability distribution shift
graph information bottleneck sufficiency necessity        ← LLM 轴 query
invariant risk minimization graph distribution shift      ← LLM 轴 query
graph rationalization explanation faithfulness benchmark
prototype learning graph neural network interpretability
Graph Information Bottleneck                              ← 方法名 grounding
Invariant Risk Minimization                               ← 方法名 grounding
Self-Interpretable Graph Neural Networks (SI-GNNs)
Self-Denoising (SD)
Explanation Ensemble (EE)
```

合并出 54 个候选，**主题高度相关**（GIB 变体 / IRM 变体 / GNN explanation benchmark BAGEL / distribution shift in explanations / invariant causal subgraph / prototype self-explainable GNN……），并召回 gold 中 **GIB @7、IRM @8**。recall@10 = **0.286**，MRR@10 = 0.143。

### 3.4 query 生成层（增强：+ 精确名查找）— 0.286，MRR 0.5

`_axis_queries_from_llm` 现同时输出 `exact_lookups`（LLM 从 workspace 方法里选出的 ≤4 个方法全名）；`_external_verify` 对它们做 **S2 精确 title 检索 + 标题验证**（`_title_verified`：query 词 ⊆ 标题词），验证命中**前置到合并列表顶部**（relevance 检索会被轴后缀稀释，精确名才能稳定命中方法论文）。真实 LLM 运行：

```
queries (12):  research question + 6 轴 query + grounding 方法名 + 方法填充
exact_lookups (4): Graph Information Bottleneck / Invariant Risk Minimization /
                   Prototype Graph Information Bottleneck / Graph Substructure Attention
```

| gold 论文 | merged rank | 来源 |
|---|---|---|
| Graph Information Bottleneck | **2** | exact lookup（`exact: Graph Information Bottleneck`）|
| Invariant Risk Minimization | **3** | exact lookup（`exact: Invariant Risk Minimization`）|
| 其余 5 篇 | — | 需 LLM 恰好生成其精确概念词（非确定性）|

**recall@10 = 0.286，MRR@10 = 0.5**（GIB/IRM 从 grounding 的 rank 7-8 前置到 top-3）。精确名查找机制验证有效：LLM 选中的方法论文稳定前置，且验证命中避免误报（如 PGIB 论文、Graph Substructure Attention 均正确前置）。

---

## 4. 本次验证发现并修复的缺陷

1. **合并语义缺陷（已修复）**：`_external_verify` 原按"主 query 先、附加 query 后"顺序合并 → 合并列表 top-10 就是主 query 的 top-10，附加 query 发现的反证全排到 11+，**永远进不了 top-10**。改为**轮转交错合并**（每 query 的 rank-1 先交错，再 rank-2……），附加 query 的发现能进入用户可见的 top-10。
2. **query 风格缺陷（已修复）**：长 prose query（research question 原文）在 S2 relevance 检索中命中率低；**简洁的方法全名**（"Graph Information Bottleneck"、"Invariant Risk Minimization"）命中率高。`_external_query_text` 改为：方法用描述性全名（all-caps 缩写从 description 首部名词短语展开，如 IRM→"Invariant Risk Minimization"）、limitation 用短 canonical_name。
3. **方法选择缺陷（部分修复）**：workspace 抽取把"命名贡献"（SubgraphX、GIB）和"架构组件"（Top-k Pool、SAG Pool、Fourier Step Function）混在一起，且 confidence 与外部检索价值不对齐（组件常 1.0）。加了组件 token 过滤（Pool/Module/Layer 等降权），但**命名贡献 vs 组件的自动区分本质上不可靠**——这是初版 query 生成层 FAIL 的根因之一。
4. **LLM 轴 query 后缀稀释（已修复）**：LLM 生成的 "graph information bottleneck sufficiency necessity" 能命中理性化论文但**漏掉方法本身**——精确的 "graph information bottleneck" 才命中 GIB@1（实测）。修复：`_external_method_full_names` 收集 workspace 方法全名，凡 LLM 轴 query 中提及的方法名，其**干净全名**也补进预算作为独立 query。效果：GIB、IRM 被召回（§3.3）。
5. **方法排序缺陷（已修复）**：原排序把单 token / 缩写方法（IRM、SubgraphX、GSAT）降权，导致 LLM 上下文看不到真实方法名。改为**仅降权组件 + 括号子模块别名**（"Self-Denoising (SD)"），其余按 confidence——真实命名方法浮上来，LLM 才能选中它们做精确查找（§3.4）。

---

## 5. 差距分析与根因

**管线不是问题，query 生成已大幅改善。** 7 篇 gold 论文各自的命中 query 均已确认存在（§3.1），轴 query 库 + 方法名 grounding + 精确名查找后，workspace 可派生的方法名（GIB、IRM）已被稳定召回并前置 top-3；剩余 5 篇需 LLM 恰好生成其精确概念词：

| gold 论文 | 命中的 query 词 | workspace 是否有此信号 |
|---|---|---|
| GIB | "graph information bottleneck" | ✅ **已召回**（方法名 grounding）|
| IRM | "invariant risk minimization" | ✅ **已召回**（方法名 grounding）|
| GREA | "graph rationalization environment augmentation" | ❌ 无（外部工作）|
| Fragile | "interpretation of neural networks fragile" | ❌ 无（图像域）|
| Sanity | "saliency maps sanity checks model randomization" | ⚠️ 有 Saliency method，但无 "sanity/robustness" 组合 |
| Reliable | "explanation uncertainty post hoc reliable" | ⚠️ 有 limitation "Existing methods ignore stability" 但用词不同 |
| PopeGNN | "explainability methods graph convolutional neural networks" | ⚠️ 有 GraphFramEx，但 query 用词不匹配 |

**根因**：
1. 抽取产物的方法名是**缩写 + 噪声**混合，LLM 轴分解能识别概念但生成的具体 query 需 grounding 到精确名才命中方法论文；
2. 长 prose query / 加后缀 query 是 S2 relevance 检索的天然劣势（精确名命中率远高）——精确名查找（§3.4）已绕开这一劣势，稳定命中 LLM 选中的方法论文；
3. 剩余 5 篇 gold（GREA / Fragile / Sanity / Reliable / PopeGNN）不是 workspace 方法，需 LLM **恰好生成**其精确概念词——LLM 非确定性使 recall 波动，这是 LLM 生成 + relevance 检索的固有边界。

---

## 6. 下一步（剩余 gap）

**研究轴 query 库 + 精确名查找已落地**，自动生成从"召回 0 / 候选噪声"提升到"**GIB/IRM 精确查找前置 top-3（MRR 0.5）/ 候选主题相关**"。剩余 gap：gold set 中 5 篇（GREA / Fragile / Sanity / Reliable / PopeGNN）需 LLM **恰好生成**其精确概念词——LLM 非确定性导致 recall 波动。

| 方案 | 说明 | 成本 |
|---|---|---|
| **轴 query 概念精确查找** | 从轴 query 提取核心名词短语（如 "graph rationalization"）做精确查找，补足 LLM 未选中的概念（dry-run 曾选中 GREA 但实际运行非确定性漏掉）| 中，需概念抽取 + 更多 S2 调用 |
| **gold set 校准** | 将 gold 中过偏的奠基论文（图像域 Fragile、跨域 GREA）换成轴上更主流的反证/重叠工作（本次已 surfacing 的 distribution-shift-in-explanations、BAGEL benchmark 等），使指标与"找相关外部工作"的产品目的对齐 | 低，但需人工复核标注 |
| **收紧抽取方法过滤** | P1 语义去重 + 方法名规范化（缩写↔全名映射表）后，方法 query 质量会显著提升 | 依赖抽取质量（Stage 1 已过）|

**建议路径**：若 Gate 目标为"主 Case 关键反证可被 Top-10 召回"，建议**校准 gold set**（方案 2）——本次 surfacing 的候选已包含 demo case 真正需要的反证/重叠工作（distribution shift in explanations、invariant causal subgraph、GNN explanation benchmark），与 gold 里部分过偏的奠基论文（图像域 Fragile）相比更贴合产品目的。若要保留现有 gold set，则做"轴 query 概念精确查找"（方案 1）。

---

## 7. 过程记录

- 2026-08-06：探测确认 7 篇 gold 论文可被对应 query 召回（GIB@1/IRM@1/GREA@2/Sanity@2/Reliable@8/PopeGNN@1）；建 gold set + runner；跑通管线层 PASS（0.857）。
- 2026-08-06：研究轴 query 库（LLM 轴分解 + 方法名 grounding）落地；auto 路径 0.0 → 0.286（GIB@7/IRM@8），候选主题相关。
- 2026-08-06：精确名查找落地（LLM 选方法名 + `_title_verified` 标题验证 + 前置合并）；GIB/IRM 前置到 top-3，MRR 0.5。
- S2 限流经验：无 key / 超频会 429，重试 backoff 不足；批量探测前先等窗口；12 query + 4 lookup ≈ 16 调用会超窗口，需分批。

## 状态更新记录

| 日期 | 内容 |
|---|---|
| 2026-08-06 | Stage 3 Gate 首跑：管线 PASS（curated 0.857）、query 生成 FAIL（auto 0.0）；修 3 缺陷（轮转合并/query 风格/组件过滤）|
| 2026-08-06 | 研究轴 query 库落地：LLM 轴分解 + 方法名 grounding，auto 0.0 → 0.286（GIB+IRM 召回，候选主题相关）；修第 4 缺陷（LLM 后缀稀释）|
| 2026-08-06 | 精确名查找落地：LLM 选方法名 + 标题验证前置，GIB/IRM top-3（MRR 0.5）；修第 5 缺陷（方法排序）|
