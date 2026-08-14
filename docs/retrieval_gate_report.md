# Retrieval Gate 验收报告

> 更新日期：2026-08-06
> 状态：完整 12 篇 demo corpus 已建；minimal Gate 通过；完整 Gate 接近达标（similar/counter 差 <0.03）
> 关联：`mvp_acceptance_and_sequence.md` Stage 2 + `docs/phase3_smoke_validation_and_next_plan.md`

---

## 1. 一页结论

| benchmark | minimal（9 篇）| **完整 demo（12+ 篇）** | Stage 2 阈值 | 完整 Gate |
|---|---|---|---|---|
| Semantic Search Recall@10 | 1.0 | **1.0** | 0.80 | ✅ 达标 |
| Similar Work Recall@10 | 1.0 | **0.889**（P2-1 修复后）| 0.80 | ✅ 达标 |
| Counter Evidence Recall@10 | 1.0 | **0.833**（P2-1 修复后）| 0.70 | ✅ 达标 |
| workspace leakage | 0 | **0** | 0 | ✅ 达标 |

**完整 demo corpus 首次跑通（2026-08-14 P2-1 修复后）**：三项全达标。修复前 similar 0.667 / counter 0.667；修复后 0.889 / 0.833。DIR / GOOD 两篇金标准仍未被召回（见 §4/§6），但已过阈，非阻塞。

---

## 2. 评测环境

| 项 | 值 |
|---|---|
| Workspace | `123100ea-e75b-4110-9048-1f5b92668c32` |
| Corpus | 12 篇 demo + 6 篇补充 = **18 篇可检索论文，595 chunks（Milvus）** |
| embedding | `BAAI/bge-m3` (1024d) |
| reranker | `BAAI/bge-reranker-v2-m3` |
| judge | `deepseek-v4-flash`（thinking disabled） |
| gold set | `evaluation/retrieval/gold/demo_sig_ood_v1.json`（完整版，refs 已对齐实际标题） |
| 完整报告 | `evaluation/retrieval/reports/demo-sig-ood-v1_20260806_212315.json` |

### 2.1 corpus 构成（18 篇）

- **Post-hoc**：GNNExplainer、PGExplainer、PGM-Explainer、SubgraphX
- **Self-interpretable / rationale**：ProtGNN、PGIB、GSAT、DIR、SunnyGNN、LogiX-GIN、Towards Prototype、TIF、VGIB、Why Self-Inconsistency
- **Evaluation**：GraphFramEx、Zorro
- **OOD**：GOOD、OOD-GNN

demo_case 12 篇全部齐（含 GSAT，2026-08-06 导入）。

---

## 3. 完整 Gate 逐 query 详情

### 3.1 Semantic Search — 全达标 ✅

| query | recall | 状态 |
|---|---|---|
| ss-001（prototype explanation） | 1.0 | ✅ |
| ss-002（IB for interpretable） | 1.0 | ✅ |
| ss-003（sufficient/necessary） | 1.0 | ✅ |

### 3.2 Similar Work — 0.889 ✅（P2-1 修复后）

| query | recall | 未召回的金标准 |
|---|---|---|
| sw-001（PGIB 的相似） | 0.667 | **DIR**（GSAT 已救回）|
| sw-002（GNNExplainer 的相似） | 1.0 | — |
| sw-003（GOOD 的相似） | 1.0 | — |

### 3.3 Counter Evidence — 0.833 ✅（P2-1 修复后）

| query | recall | 未召回的金标准 |
|---|---|---|
| ce-001（prototype vs IB） | 1.0 | —（Zorro 已救回）|
| ce-002（IB stability） | 1.0 | — |
| ce-003（constraints/accuracy） | 0.5 | **GOOD**（recall 层无法召回，见 §6）|

---

## 4. 差距分析（2026-08-14 修复后更新）

**根因**（经 `scripts/diag_retrieval_loss.py` / `diag_counter_loss.py` 逐步定位，2026-08-14）：

1. **槽位浪费（主要根因）**：rerank 只返回 top-10 *chunk*，同一篇论文的多条 chunk 占掉多个槽位 → top-10 装不满 10 篇不同论文。Zorro（counter）、PGM-Explainer（similar）等金标准的 chunk 其实在召回池里、rerank 排在 11+，被重复论文挤掉。
2. **reranker 过于"窄"（similar 特有）**：similar work 的 rerank query 用论文第一个 sample chunk（PGIB 的引言偏"prototype+IB"表述），把同领域但表述不同的 GSAT/DIR 排低——即使 rerank 全部候选也救不回（原始 Milvus 分反而能进 top-10）。
3. **GOOD 召回层不可救**：对 claim 的 vector recall top-80 里根本没有 GOOD 的 chunk（OOD benchmark 论文与 claim 措辞距离过大），over-fetch 无法解决。

修复后仍漏的 2 篇：**DIR**（similar，语义距离确实远）、**GOOD**（counter，recall 层不可救）。已过阈，非阻塞。

**结论**：不是 pipeline 坏（semantic 全过、leakage=0、minimal 全过），是**跨家族相似度/反证召回**的调优空间。P2-1 修复后三项全达标。

---

## 5. 过程记录（2026-08-06 扩 corpus）

### 5.1 从 Semantic Scholar 导入缺失论文

- 通过 `POST /workspaces/{wid}/papers/import-from-s2` 导入 8 篇（GNNExplainer/PGExplainer/PGM-Explainer/SubgraphX/GraphFramEx/Zorro/GOOD/OOD-GNN）+ 手动补 2 篇 arXiv PDF（GraphFramEx/GOOD 的 OA 下载失败，改从 arxiv.org 下载 attach）
- GSAT 单独导入（demo 12 篇缺它）

### 5.2 修复 SubgraphX 解析 bug（pdf_parser）

- **根因**：SubgraphX 的 arXiv PDF 标题字号 **11.95pt**，旧阈值 `avg_size >= 12.0` 拒判 → 只 chunk 出 4 个 Appendix chunks，正文丢失
- **修复**：`pdf_parser.py` is_large 阈值从 `>= 12.0` 降到 `>= 11.5`（正文通常 ~10pt，标题 11.5+，安全）
- **验证**：SubgraphX 4 → **31 chunks**（检测到 Abstract/Introduction/Related Work/Conclusion/References/Appendix 6 个 section）
- **重新走完整 pipeline**：`scripts/fix_subgraphx.py`（重新 parse → 新 md → 新 chunks → 重建索引 → 软删旧 items → 重新 extract）

### 5.3 其他

- demo gold set 的 paper_refs 对齐 workspace 实际标题（缩写/变体），12 refs 全解析
- **运行注意**：run_eval 必须从 `backend/` 目录跑（.env 在 backend，从 repo 根跑 SILICONFLOW_API_KEY 为空）

---

## 6. P2-1 召回修复（2026-08-14）

**目标**：similar ≥0.80、counter ≥0.70。

**改动**（`app/domains/retrieval/service.py`）：
1. **`_paper_max_top_k`**（similar + counter）：rerank 全部召回候选 → 每篇论文取最高分 chunk → 取 top-k 篇。让 top-k 槽位装 k 篇**不同论文**（Gate 的 recall@10 按去重论文算；之前同一论文的多 chunk 浪费槽位）。
2. **`_hybrid_rerank_top_k`**（similar 专用）：raw Milvus 分 + rerank 分各 0.5 min-max 融合 → 每篇最高 → top-k。救回被 reranker 因表述差异排低的同主题论文（GSAT）。
3. counter 的 recall_k 保持 top_k*3（GOOD 连 recall top-80 都不在，over-fetch 无效，未改）。

**效果**（完整 demo corpus，两轮验证稳定）：

| benchmark | 修复前 | 修复后 | 阈值 |
|---|---|---|---|
| Similar Work | 0.667 | **0.889** | 0.80 ✅ |
| Counter Evidence | 0.667 | **0.833** | 0.70 ✅ |

救回：PGM-Explainer（similar）、Zorro（counter）、GSAT（similar，边界 rank8-10）。仍漏：DIR（similar 语义距离远）、GOOD（counter recall 层不可救）。+8 单测（`_paper_max_top_k` ×5 + `_hybrid_rerank_top_k` ×3），389 后端测试全过。

**诊断工具**（保留）：`scripts/diag_retrieval_loss.py`、`scripts/diag_counter_loss.py`（只读，逐步定位金标准论文丢失环节）。

---

## 7. 状态与下一步

| 项 | 状态 |
|---|---|
| minimal Gate（9 篇） | ✅ 全过（1.0/1.0/1.0） |
| 完整 demo corpus | ✅ 已建（18 篇） |
| 完整 demo Gate | ✅ **全过（1.0 / 0.889 / 0.833，leakage 0）** |
| 下一步 | 进入 Stage 3 外部新颖性核验 / Stage 4 Opportunity 正式生成；DIR/GOOD 可作 gold 校准讨论项 |

**完整 Gate 达标后** → 进入 Stage 3 外部新颖性核验 / Stage 4 Opportunity 正式生成（见 `docs/discover_agent_product_and_implementation_plan.md` 状态更新）。

## 状态更新记录

| 日期 | 内容 |
|---|---|
| 2026-08-06 | 扩 corpus 到 18 篇；修 SubgraphX 解析 bug；完整 demo Gate 首次跑通（semantic 1.0 / similar 0.78 / counter 0.67 / leakage 0） |
| 2026-08-14 | **P2-1 召回修复**：`_paper_max_top_k`（论文级去重）+ `_hybrid_rerank_top_k`（raw+rerank 融合，similar 用）；完整 demo Gate 全过（1.0 / 0.889 / 0.833，leakage 0），两轮稳定 |
