# GapMind 权威知识源台账（待冻结版）

**版本**：v0.1（2026-08-24）
**状态**：模板已建立，资料元数据、许可和文本哈希仍需项目负责人逐条核验
**原则**：Gold、Demo 和离线快照只能引用已登记且可追溯的资料。

## 1. 登记字段

| 字段 | 要求 |
|---|---|
| `source_id` | 稳定 ID，不能只用文件名 |
| `title/authors` | 与出版物或官方元数据一致 |
| `venue/year/doi/url` | 至少一种可复核的权威定位，最好同时保留 DOI/官方 URL |
| `source_type` | `paper`、`dataset`、`official_doc`、`external_index` 等 |
| `version/published_at/retrieved_at` | 区分原始版本和本次获取时间 |
| `license` | 记录明确许可、未知或需人工确认 |
| `full_text` | `full`、`metadata_only`、`abstract_only` |
| `sensitivity` | L0-L3，遵循数据分级文档 |
| `sha256` | 对实际导入文件或标准化文本计算 |
| `workspace_id/snapshot_id` | 关联到冻结 Demo/评测快照 |
| `review_status/reviewer` | `pending`、`reviewed`、`rejected` |
| `remote_allowed` | 是否允许向远程模型发送片段 |
| `notes` | 解析异常、授权限制、替代来源 |

## 2. 当前已知引用集合

以下集合来自仓库中现有 Gold/评测文件，只说明“代码引用了这些标识”，不等于已完成授权和全文核验：

| 集合 | 代码位置 | 当前用途 | 冻结状态 |
|---|---|---|---|
| `gnn-explanation-9papers` | `evaluation/chat/gold/gnn_explanations_gold_v2.json`、`evaluation/retrieval/gold/minimal_gnn_v1.json` | Workspace Chat/检索 Gold | 题目结构已存在；论文元数据、文件哈希待补 |
| `demo_sig_ood_external_v1` | `evaluation/external/gold/demo_sig_ood_external_v1.json` | Semantic Scholar 外部核验 Gold | S2 标识已存在；获取时间、返回快照待补 |
| Gap Board 研究空白材料 | `backend/data/chunks/`、`data/chunks/`（本地忽略目录） | 垂类抽取与棋盘 | 真实内容未纳入仓库，禁止直接作为提交证据 |

## 3. 单条登记模板

```yaml
source_id: pending-001
title: ""
authors: []
venue: ""
year: null
doi: ""
official_url: ""
source_type: paper
version: ""
published_at: ""
retrieved_at: ""
license: pending_manual_review
full_text: full | metadata_only | abstract_only
sensitivity: L0
sha256: ""
snapshot_id: ""
workspace_id: ""
review_status: pending
reviewer: ""
remote_allowed: false
notes: ""
```

## 4. 冻结前验收

- [ ] Demo 每一个论文/资料都能在台账中找到。
- [ ] 至少 12—20 个 Gold 问题都能回链到 `source_id` 和证据片段。
- [ ] 全文资料的许可和远程处理边界已人工确认。
- [ ] 已生成实际文件/标准化文本 SHA-256，并记录导入时间。
- [ ] 已区分仓库中 Gold 定义与开发机 `data/` 临时索引，未将后者冒充可复现快照。
- [ ] 快照 manifest、导入顺序和索引构建日志已进入提交包或受控下载清单。
