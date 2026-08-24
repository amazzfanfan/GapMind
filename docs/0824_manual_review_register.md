# GapMind 典型问题人工审查登记

**版本**：v0.1（2026-08-24）
**来源**：`evaluation/chat/reports/gnn_explanations_gold_v2_report.json`。
**范围限制**：当前只有 5 题；正式 P0 目标是 12—20 题，并需追加真实用户/领域专家或第二轮盲评。

## 1. 已有 5 题结果

| 题号 | 预期行为 | 当前人工 verdict | 机械引用/来源检查 | 备注 |
|---|---|---|---|---|
| `chat-gnn-03` | supported | supported | passed | 自解释 GNN 方法与论文引用 |
| `chat-gnn-04` | supported | supported | passed | GIB 目标/公式 |
| `chat-gnn-05` | supported | supported | passed | ProtGNN sep/div 损失 |
| `chat-gnn-06` | supported | supported | passed | PGIB 公式 |
| `chat-gnn-07` | insufficient_evidence | insufficient_evidence | passed | 分布变化下解释稳定性，避免过度结论 |

报告中的观测摘要：5/5 有观测，paper citation validity=1.0，required paper coverage=1.0，source marker validity=1.0，human verdict coverage=1.0，human verdict accuracy=1.0，retrieval audit coverage=1.0；这些是该文件的样本内结果，不能外推到更大题集。

## 2. 复核要求

- [ ] 核对每题的标准答案是否来自已登记 source 和允许的证据片段。
- [ ] 至少由第二位评审盲审 3 个支持题和 1 个不足证据题。
- [ ] 记录分歧、修改原因和 Gold 版本；不得根据一次回答反向改 Gold。
- [ ] 添加相似工作、反证、机会核验、计划草稿和服务降级题。
- [ ] 追加 7—15 题后重新运行，目标总数 12—20。
