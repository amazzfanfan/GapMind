# RG-1 三篇论文人工抽取质量审查 — 核验结果

> 核验日期：2026-08-04
> 方法：按 `docs/rg1_extraction_review.md` 手册执行
> 数据源：`docs/knowledge_items.md` 导出的 103 个 items + Postgres `evidence_spans` + 磁盘 parsed_markdown artifact
> 结论：**回链精确 100% 达标；发现系统性方法实体去重失败，需修复抽取管线**

---

## 一、回链精确性核验（Step 2）

读取三篇论文的 parsed_markdown artifact，逐一验证 `content[start_char:end_char] == evidence_spans.text`：

| 论文 | 论文ID | artifact | spans | 精确 | 不匹配 |
|---|---|---|---|---|---|
| PGIB | 6dbc57ff | parsed_markdown (61596 chars) | 24 | **24** | 0 |
| SunnyGNN | c1876121 | parsed_markdown (41372 chars) | 17 | **17** | 0 |
| RAG vs GraphRAG | 8eb9634d | parsed_markdown (90373 chars) | 62 | **62** | 0 |
| **合计** | | | **103** | **103** | **0** |

**✅ 回链精确性 100% 达标**（手册验收标准 #1 满足）

---

## 二、逐篇审查记录

> 审查范围：每篇的 method + claim + limitation（dataset/task 风险较低，本次抽查少量）。判断：✅正确 / 🟡部分正确 / ❌错误 / ⚠️应拒绝但接受（重复）/ 💤应接受但拒绝

### 2.1 PGIB（抽查 15 项：6 method + 6 claim + 3 limitation）

| item_id | type | canonical_name | 回链 | 判断 | 备注 |
|---|---|---|---|---|---|
| 9f3a68a8 | method | PGIB | ✅ | ✅正确 | 框架介绍，description 贴合原文 |
| 2352f402 | method | PGIB | ✅ | ⚠️应拒绝但接受 | **与 9f3a68a8 同名 PGIB**，内容描述 merging 变体，应并入同一 CanonicalEntity 的第二个 Mention |
| 6e1dfebd | method | PGIBcont | ✅ | 🟡部分正确 | description 含 **推测**"likely with continuous prototype vectors"，证据只有"ablation studies"一句 |
| 7369350c | method | GSAT | ✅ | ✅正确 | |
| 09f998db | method | ProtGNN | ✅ | ✅正确 | |
| 98f8d7bd | method | VGIB | ✅ | ✅正确 | |
| 589c3f92 | claim | Connectivity loss improves performance | ✅ | ✅正确 | statement 与证据一致 |
| 5a95f88a | claim | Contrastive prototypes more distinguishable | ✅ | 🟡部分正确 | conditions 加"compared to variational IB loss"，**证据 span 无此对比** |
| 8968788e | claim | First work combining prototype learning and IB | ✅ | ✅正确 | |
| 7e32106c | claim | Merging prototypes enhances interpretability | ✅ | 🟡部分正确 | statement 加"while reducing model complexity"，**证据 span 无此点** |
| 0d5b9bea | claim | Merging prototypes improves performance and interpretability | ✅ | ✅正确 | |
| 5c02c373 | claim | PGIB outperforms SOTA | ✅ | ✅正确 | 忠实原文 comparative 主张 |
| 3f40af12 | limitation | Hyperparameter sensitivity of alpha2 | ✅ | ✅正确 | |
| 0af01451 | limitation | PGIB lacks domain knowledge integration | ✅ | ✅正确 | |
| 1b62fe5c | limitation | Prototype semantics duplication | ✅ | ✅正确 | |

**PGIB 统计**：正确 11 / 部分正确 3 / 错误 0 / 应拒绝但接受（重复）1 / 应接受但拒绝 0

### 2.2 SunnyGNN（抽查 9 项：2 method + 5 claim + 2 limitation）

| item_id | type | canonical_name | 回链 | 判断 | 备注 |
|---|---|---|---|---|---|
| 0027167f | method | SUNNY-GNN | ✅ | ✅正确 | 框架总览 |
| cc3bb9db | method | SUNNY-GNN | ✅ | ⚠️应拒绝但接受 | **与 0027167f 同名 SUNNY-GNN**，应并入同一实体第二个 Mention |
| e856be49 | claim | complex graph claim | ✅ | ✅正确 | |
| 1297f055 | claim | contrastive learning claim | ✅ | ✅正确 | |
| 86f43cda | claim | performance improvement claim | ✅ | ✅正确 | 3.5% / 13.1% 数字来自同句 |
| 7ba48e09 | claim | problem identification claim | ✅ | ✅正确 | |
| a7dcd5d5 | claim | robustness claim | ✅ | ✅正确 | |
| 009bb904 | limitation | SUNNY-GNN limited to simple scenarios | ✅ | 🟡部分正确 | description 加"extended to heterogeneous…preliminary results"，**证据 span 无此句** |
| 7d02d862 | limitation | application scope limitation | ✅ | ⚠️应拒绝但接受 | **与 009bb904 共用同一证据 span (36374, 36457)**，内容近同，重复 |

**SunnyGNN 统计**：正确 6 / 部分正确 1 / 错误 0 / 应拒绝但接受（重复）2 / 应接受但拒绝 0

### 2.3 RAG vs GraphRAG（抽查 44 项：23 method + 13 claim + 8 limitation）

**方法（23 项）——重名严重：**

| 方法名 | 出现次数 | 判断 |
|---|---|---|
| RAG | 3 | ⚠️保留 1，2 个重复 |
| Community-GraphRAG (Global) | 2 | ⚠️保留 1 |
| Community-GraphRAG (Local) | 2 | ⚠️保留 1 |
| HippoRAG2 | 2 | ⚠️保留 1 |
| KG-GraphRAG (Triplets only) | 2 | ⚠️保留 1 |
| KG-GraphRAG (Triplets+Text) | 2 | ⚠️保留 1 |
| RaptorRAG | 2 | ⚠️保留 1 |
| 其余 8 个唯一方法 | 1 | ✅正确 |

**主张（抽查代表性 13 项）**：多数 ✅正确；发现 2 个问题：
- `Hybrid strategies improve QA consistently` (ad336390)：statement 是**残缺句**（缺主语，从 evidence 中段截取）→ 🟡
- `RAG and GraphRAG exhibit complementary behaviors` (86772da0) 与 `Complementary strengths of RAG and GraphRAG` (31775c6c) **近重复**（同一结论两个 claim）→ ⚠️

**局限（8 项）——发现 3 组重复：**
- `KG construction incompleteness` (a69e3062) 与 `KG-GraphRAG limited graph coverage` (b2792fe8)：**内容近同**（都讲 KG 覆盖率 65.8%/65.5%）→ ⚠️保留 1
- `LLM-as-a-Judge position bias` (7fb2aa8a) 与 `Position effects in LLM-as-a-Judge` (d0dac236)：**重复**，且 7fb2aa8a 与 claim `4f8ba01f` **共用同一证据 span (7082, 7323)**（同事实既抽成 claim 又抽成 limitation）→ ⚠️保留 1
- `GraphRAG sensitive to graph construction quality` (7f1d3689) 与 `Incomplete or noisy graph construction` (422b85bf)：**近重复**（都关于图构建质量）→ ⚠️保留 1

**RAG vs GraphRAG 统计**：正确 ~28 / 部分正确 1 / 错误 0 / 应拒绝但接受（重复）~14 / 应接受但拒绝 0

---

## 三、系统性发现（主问题）

### 🔴 发现 1：方法实体去重失败（三篇论文全部中招）

同一 `canonical_name` 生成了多个独立 method item，违反 `mvp_core_spec.md` §2.2 的 CanonicalEntity 规则（同一方法应只有一个 CanonicalEntity + 多个 PaperMention）：

| 论文 | 重名方法 | 影响 |
|---|---|---|
| PGIB | PGIB × 2 | 框架介绍 + merging 变体分裂成两个实体 |
| SunnyGNN | SUNNY-GNN × 2 | 框架总览 + 方法细节分裂 |
| RAG vs GraphRAG | RAG ×3、Community-GraphRAG (Global) ×2 等 7 个名字 | **23 个 method 里 15 个是重名** |

**根因**：`_write_extraction` 的去重键是 `(type, canonical_name, start_char, end_char)`，不同 batch 抽到同一方法（intro batch vs method batch）→ 不同 span → 不同 item。LLM 在多个 batch 重复抽取了同一方法。

**影响**：知识图谱里同一方法出现多个节点，下游 Discover/检索会把同一方法的多个 mention 当多个实体，污染相似工作聚合。

### 🟡 发现 2：claim/limitation 证据 span 碰撞

- SunnyGNN：span (36374, 36457) 被 2 个 limitation 共用
- RAG vs GraphRAG：span (7082, 7323) 被 1 claim + 1 limitation 共用（同事实双类型抽取）

### 🟡 发现 3：少量内容越界（超出证据 span）

- PGIBcont description 的"likely with continuous prototype vectors"（推测）
- 2 个 PGIB claim、1 个 SunnyGNN limitation 在 content 里加了证据 span 没有的细节

### 🟡 发现 4：1 个 claim statement 是残缺句

- RAGvsGraphRAG 的 `Hybrid strategies improve QA consistently` 从 evidence 中段截取，缺主语

---

## 四、验收对照

| 手册验收项 | 结果 |
|---|---|
| 回链精确 100% | ✅ 103/103 精确 |
| 错误 claim 被标 human_confirmed | ✅ 无（全部仍为 extracted_candidate） |
| 系统性问题处理 | 🔴 **发现 1（方法去重失败）需要修复** |

## 五、建议的修复路径

**P0 — 修实体去重（阻塞后续 Discover 质量）：**
1. `_write_extraction` 或 `_normalize_relation_type` 加**实体级去重**：同一 workspace 内，`(type, normalized_canonical_name)` 相同的 method/task/dataset，合并到同一个 CanonicalEntity + 追加 PaperMention，而不是新建 item
2. 跨 batch 去重键从 `(type, name, span)` 改为 `(type, name)` + "已有同一实体则 upsert mention"
3. 重跑三篇论文抽取，验证 method 节点数收敛到唯一

**P1 — 收敛越界内容：**
1. `extract_v1.py` prompt：给 claim 加"不得添加证据中未出现的条件或数字"；给 method 加"description 只写证据支持的描述，禁止推测"
2. claim statement 要求完整句（不从 evidence 中段截取）

**P1 — 去重后续验证：**
1. 修复后重跑本审查的重复项（PGIB×2 / SUNNY-GNN×2 / RAG 组 / KG 覆盖率组 / LLM-as-a-Judge 组）
2. 确认每个重复组只剩 1 个 item

## 状态更新记录

| 日期 | 内容 |
|---|---|
| 2026-08-04 | 首轮人工审查完成：回链 100% 达标；方法去重失败待修复（P0） |
