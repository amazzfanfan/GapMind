# Retrieval Gate 验收报告

> 更新日期：2026-08-06
> 状态：完整 12 篇 demo corpus 已建；minimal Gate 通过；完整 Gate 接近达标（similar/counter 差 <0.03）
> 关联：`mvp_acceptance_and_sequence.md` Stage 2 + `docs/phase3_smoke_validation_and_next_plan.md`

---

## 1. 一页结论

| benchmark | minimal（9 篇）| **完整 demo（12+ 篇）** | Stage 2 阈值 | 完整 Gate |
|---|---|---|---|---|
| Semantic Search Recall@10 | 1.0 | **1.0** | 0.80 | ✅ 达标 |
| Similar Work Recall@10 | 1.0 | **0.778** | 0.80 | ❌ 差 0.02 |
| Counter Evidence Recall@10 | 1.0 | **0.667** | 0.70 | ❌ 差 0.03 |
| workspace leakage | 0 | **0** | 0 | ✅ 达标 |

**完整 demo corpus 首次跑通**：semantic 达标，similar/counter 接近但未达阈值。差距来自 4 篇金标准论文（DIR / PGM-Explainer / Zorro / GOOD）未被 top-10 召回——真实召回问题，非标注问题。

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

### 3.2 Similar Work — 0.778 ❌

| query | recall | 未召回的金标准 |
|---|---|---|
| sw-001（PGIB 的相似） | 0.667 | **DIR** |
| sw-002（GNNExplainer 的相似） | 0.667 | **PGM-Explainer** |
| sw-003（GOOD 的相似） | 1.0 | — |

### 3.3 Counter Evidence — 0.667 ❌

| query | recall | 未召回的金标准 |
|---|---|---|
| ce-001（prototype vs IB） | 0.5 | **Zorro** |
| ce-002（IB stability） | 1.0 | — |
| ce-003（constraints/accuracy） | 0.5 | **GOOD** |

---

## 4. 差距分析

4 篇金标准论文未进 top-10，都是**召回层**问题（vector recall 后 rerank/judge 仍排不进 top-10）：

| 论文 | 场景 | 可能原因 |
|---|---|---|
| DIR | PGIB 的 similar_work | invariant rationale 方法与 prototype+IB 语义距离较远 |
| PGM-Explainer | GNNExplainer 的 similar_work | 同为 post-hoc 但机制（PGM vs edge mask）差异大 |
| Zorro | prototype-vs-IB 反证 | evaluation 论文与 claim 措辞距离大 |
| GOOD | constraints/accuracy 反证 | OOD benchmark 论文与 claim 距离大 |

**结论**：不是 pipeline 坏（semantic 全过、leakage=0、minimal 全过），是**跨家族相似度/反证召回**的调优空间。差距小（0.02/0.03），调 recall over-fetch 或 reranker 权重有望过线。

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

## 6. 状态与下一步

| 项 | 状态 |
|---|---|
| minimal Gate（9 篇） | ✅ 全过（1.0/1.0/1.0） |
| 完整 demo corpus | ✅ 已建（18 篇） |
| 完整 demo Gate | 🟡 semantic 过，similar/counter 差 <0.03 |
| 下一步 | 调 similar/counter 召回（over-fetch 4x→6x 或 reranker 权重），目标过线；或接受当前作为 baseline 继续 |

**完整 Gate 达标后** → 进入 Stage 3 外部新颖性核验 / Stage 4 Opportunity 正式生成（见 `docs/discover_agent_product_and_implementation_plan.md` 状态更新）。

## 状态更新记录

| 日期 | 内容 |
|---|---|
| 2026-08-06 | 扩 corpus 到 18 篇；修 SubgraphX 解析 bug；完整 demo Gate 首次跑通（semantic 1.0 / similar 0.78 / counter 0.67 / leakage 0） |
