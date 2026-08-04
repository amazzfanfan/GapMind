# Retrieval Gate 评测框架

Stage-2 Gate 判据（来自 `docs/phase3_smoke_validation_and_next_plan.md` §6 V2）：

| 指标 | 阈值 |
|---|---|
| Semantic Search Recall@10 | ≥ 0.80 |
| Similar Work Recall@10 | ≥ 0.80 |
| Counter Evidence Recall@10 | ≥ 0.70 |
| workspace leakage | = 0 |
| 结果可回链 | Paper + artifact |

## 目录结构

```
evaluation/retrieval/
├── gold_set.py        # GoldSet Pydantic schema（gold JSON 的校验器）
├── metrics.py         # 纯函数指标：Recall@K / MRR / nDCG / diversity / leakage
├── run_eval.py        # Gate runner：加载 gold → 跑三个检索函数 → 出报告
├── gold/              # 人工标注的 gold set（用论文标题引用，运行时解析为 UUID）
│   └── demo_sig_ood_v1.json
├── eval_queries.json  # 遗留 stub（FILL_ME 占位），已被 gold/ 取代，勿用
└── reports/           # 每次评测 JSON 报告（gitignored，不入库）
```

## 运行

需要：backend 依赖、PostgreSQL + Milvus 已启动、目标 workspace 的 corpus 已解析+索引。

```bash
# 完整 Gate（跑 LLM judge）
python evaluation/retrieval/run_eval.py \
    --workspace-id <uuid> \
    --gold evaluation/retrieval/gold/demo_sig_ood_v1.json

# 便宜 smoke（跳过 judge，测 Recall 链路）
python evaluation/retrieval/run_eval.py \
    --workspace-id <uuid> \
    --gold evaluation/retrieval/gold/demo_sig_ood_v1.json \
    --minimal
```

退出码：`0` = Gate 全部通过；`2` = 有 benchmark 未达标。报告写到 `reports/<case_id>_<时间戳>.json`。

## 写一个新 gold set

1. 复制 `gold/demo_sig_ood_v1.json` 为 `gold/<case_id>.json`
2. 填 `case_id` / `corpus_version` / `workspace_hint` / `freeze`（冻结模型+chunk 版本）
3. 三类 benchmark：
   - `semantic_search`: `query` + `target_paper_ref`（目标论文）
   - `similar_work`: `source_paper_ref` + `relevant_paper_refs`（paper-level relevant）
   - `counter_evidence`: `claim_text` + `source_paper_ref` + `gold_roles`（`{paper_ref, role}`，role ∈ contradicts/qualifies/supports/overlaps/unknown）
4. `paper_ref` 用论文标题（最易读），运行时按 标题 → external_paper_id → UUID 顺序解析
5. 跑之前先人工核对每篇论文确实在目标 workspace 里（未解析的 ref 会 WARN 并跳过）

## 测试

```bash
cd backend && python -m pytest tests/test_retrieval_gate_metrics.py tests/test_retrieval_gold_set.py -v
```

## 约定

- gold set 是**冻结事实**：跑完一个 Gate 后不要改已有 query 的标注，新增 query 用新 `query_id`
- 报告必须记录 `freeze`（模型/chunk 版本），版本变了报告不可比
- `workspace_leakage` 必须为 0；任何 > 0 都是隔离缺陷，不是调参项
