# GapMind 知识库快照 Manifest（待冻结版）

**版本**：`snapshot-pending-v1`
**状态**：结构已建立；实际资料、哈希、索引构建日志和恢复演练待完成
**目的**：让 Demo 不依赖某台开发机的 `storage/`、`data/chunks/` 或不可追溯的 Milvus 状态。

## 1. 快照元信息

```yaml
snapshot_id: snapshot-pending-v1
created_at: 2026-08-24
branch: yx_dev
git_commit: pending_freeze_commit
schema_head: pending_recheck
parser: PyMuPDF-1.24.10
embedding_model: BAAI/bge-m3
embedding_dimension: 1024
reranker_model: BAAI/bge-reranker-v2-m3
chunker_config: pending_record
workspace_id: pending_demo_workspace
paper_count: null
chunk_count: null
milvus_collection: pending
remote_transfer_policy: docs/0824_data_classification_and_remote_calls.md
```

## 2. 快照内容清单

| 内容 | 路径/标识 | 是否纳入提交包 | 状态 |
|---|---|---:|---|
| 论文元数据清单 | `sources.csv` 或 `sources.json` | 是 | 待生成 |
| 许可与远程调用标记 | `source_registry` | 是 | 待核验 |
| 脱敏 PDF/标准化文本 | `materials/` 或受控下载地址 | 视许可 | 待选择 |
| 导入顺序 | `import_order.json` | 是 | 待生成 |
| 解析摘要 | `parse_report.json` | 是 | 待生成 |
| Chunk 摘要/哈希 | `chunk_manifest.json` | 是 | 待生成 |
| 向量模型与维度 | 本文件 | 是 | 已知，冻结时重验 |
| Milvus 集合构建记录 | `index_build_report.json` | 是 | 待生成 |
| Gold 问题与标准证据 | `gold/` | 是 | 部分已存在 |

## 3. 构建与恢复步骤

1. 在干净工作区准备已获授权的最小资料集。
2. 逐条登记来源、许可、敏感等级和 SHA-256。
3. 按固定顺序导入论文，记录解析成功/失败页和 chunk 数量。
4. 用固定 embedding/reranker 配置建立索引，记录集合名和构建时间。
5. 导入 Gold 问题，运行离线检索评测和人工抽查。
6. 清空测试 workspace 或使用新数据库，按提交包手册恢复一次。
7. 对比论文数、chunk 数、关键证据 ID 和三条 Demo 路径；不一致则不能标记冻结。

## 4. 禁止事项

- 不把当前开发机上未经登记的 1044 个 chunk 目录直接写成比赛快照。
- 不把 Milvus 中仅存在于本地容器的数据当作可复现输入。
- 不把 Gold JSON 的论文标识等同于已获取全文或已获得再分发许可。
- 不在没有恢复演练的情况下宣称“换机可复现”。
