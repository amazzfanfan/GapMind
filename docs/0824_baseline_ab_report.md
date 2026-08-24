# GapMind 检索/Chat 基线与对照记录

**版本**：v0.1（2026-08-24）
**状态**：记录已有离线报告；不可替代最终同题、同 top-k 的冻结 A/B。

## 1. 已有可追溯结果

### Retrieval Gate：向量召回 smoke（top-k=10）

来源：`evaluation/retrieval/reports/minimal_gnn_gate_baseline.json`。
语料：`gnn-explanation-9papers`；workspace：`123100ea-e75b-4110-9048-1f5b92668c32`；运行时间：2026-08-24T13:10:39Z。

| 任务 | Recall@10 | 阈值 | workspace leakage | 结论 |
|---|---:|---:|---:|---|
| Semantic Search | 1.0000 | 0.80 | 0 | 达标 |
| Similar Work | 0.6667 | 0.80 | 0 | 未达标 |
| Counter Evidence | 1.0000 | 0.70 | 0 | 达标 |

这组报告 `minimal=true`，跳过 LLM judge；总体 Gate 未通过，原因是 Similar Work 未达到阈值。它适合作为风险基线，不应包装成完整效果结论。

### 完整检索链：reranker/judge（top-k=15）

来源：`evaluation/retrieval/reports/minimal_gnn_gate_full_top15.json`。
Semantic Search Recall@15=1.0000、Similar Work Recall@15=0.6667、Counter Evidence Recall@15=1.0000，leakage=0；Gate 仍未通过。由于 top-k 与 smoke 组不同，只能说明当前链路的观测，不构成严格 A/B 因果比较。

### Facet A/B 与 Chat

- `evaluation/retrieval/reports/minimal_gnn_facet_ab_draft.json` 标记 `experiment_usable=false`，固定 Gold 没有 facet cases，不能据此证明 facet 提升。
- `evaluation/retrieval/reports/chat_gnn_facet_ab_draft.json` 的 5 题均因 `embedding_unavailable` 失败，且 `annotation_status=draft`，不能用于生成质量结论。
- `evaluation/chat/reports/gnn_explanations_gold_v2_report.json` 的 5 个观测题机械引用检查通过、人工 verdict 覆盖为 1.0；这证明引用/标记链条的一次已保存观测，不代表 12—20 题的总体质量。

## 2. 最终 A/B 执行协议

### 2.1 离线评测器复核（2026-08-25）

使用仓库内的 `evaluation/chat/run_eval.py`，以 `gnn_explanations_gold_v2.json` 和已保存的 `gnn_explanations_v2_reviewer2_reviewed.json` 重新运行一次离线报告：

| 项目 | 结果 |
|---|---|
| 题数 | 5 |
| 机械检查 | `mechanical_passed=true` |
| 人工 verdict 覆盖 | `1.0` |
| 是否调用 LLM/Milvus/数据库 | 否 |
| 证明范围 | 评测器和已保存观测可复现，不证明当前候选版本在 12—20 题上的总体效果 |

这次复核的退出码为 `0`，但输入仍是历史保存观测；它不能替代同一冻结快照下的新增 Gold、实时 A/B 或第二评审盲评。

固定同一 snapshot、Gold、workspace、query 顺序和 `top_k`，只改变一个变量：

| 组 | Embedding | Reranker | Judge | 目的 |
|---|---|---|---|---|
| A | BGE-m3 | 关闭 | 关闭/固定 | 向量召回基线 |
| B | BGE-m3 | 开启 | 与 A 相同 | 测试重排收益 |
| C（可选） | BGE-m3 | 开启 | 开启 | 测试反证角色判定，不与 Recall 混为一谈 |

每组至少保存：命令、commit、模型配置、Gold hash、运行时间、每题结果、失败码、Recall@k、MRR/nDCG、paper diversity 和 leakage。若依赖不可用，记录 `failed/degraded`，不删除样本。

## 3. 结论规则

- 只有 A/B 使用同一题集且 `experiment_usable=true` 时，才写“提升/下降”。
- Similar Work 当前存在未达标风险，不能在 PPT 中写“相似工作准确率已达到阈值”。
- leakage 只要大于 0 就是隔离缺陷，不是调参问题。
- Chat 的 `human_verdict` 为空或 Gold 为 draft 时，不进入生产阈值。
