# GapMind 候选版本冻结清单

**记录日期**：2026-08-25
**分支**：`yx_dev`
**状态**：预冻结候选，尚未形成最终提交 commit；本文件记录当前代码和材料状态，不代表生产环境已验证。

## 1. 代码与数据库版本

| 项目 | 当前值 | 证据/边界 |
|---|---|---|
| 当前 HEAD | `07efdb7` `docs: 整理比赛交付材料与方案初稿` | 当前 P0 加固仍在工作区，最终提交 commit 待用户审查授权 |
| 工作区 | 有业务代码、测试、前端类型和 docs 修改；`deploy/`、比赛 PDF、根目录 `index.html` 为受保护既有材料 | 以 `git status --short` 为准；不得使用 `git add .` |
| 分支 | `yx_dev` | 未 push |
| Alembic head | `0028_search_acl` | 已通过 `backend/.venv/Scripts/alembic.exe heads` 查询；真实数据库升级待 staging 验证 |
| 新迁移 | `0025_workspace_owner_acl`、`0026_paper_parse_quality`、`0027_chat_conversation_owner`、`0028_search_acl` | 分别对应 Workspace owner、PDF 解析质量、Chat 对话 owner、搜索历史/收藏 owner 隔离 |

## 2. 自动化验证快照

以下结果已在当前工作区执行，属于代码级验证；未替代真实服务、真实用户和现场 Demo 证据。

| 检查 | 结果 | 备注 |
|---|---:|---|
| 后端全量测试 | **481 passed, 2 warnings** | `backend/.venv/Scripts/python.exe -m pytest tests -q` |
| 前端测试 | **17 files / 56 passed** | `npm test -- --run` |
| TypeScript | 通过 | `npm run typecheck` |
| 前端构建 | 通过 | 仍有主包约 1.83 MB 的 Vite chunk 警告，归入 P1 性能取舍 |
| ESLint | 0 errors / 14 warnings | 警告仍需在限制说明中保留 |
| OpenAPI 类型 | 已重新生成 | `npm run gen:api`，生成 87 routes / 380922 bytes |
| Python 编译 | 通过 | `compileall -q app alembic` |
| 工作区空白检查 | 通过 | `git diff --check`；保留换行符提示，不视为业务错误 |

迁移验证边界：`alembic heads` 已确认候选 head 为 `0028_search_acl`；临时 SQLite 从零升级在既有 `0004_paper_parse_state` 的非 batch ALTER 处停止，不能替代目标 PostgreSQL 15 的 staging 升级验证。

## 3. 模型、服务和调用约束

| 组件 | 当前口径 | 尚未冻结的证据 |
|---|---|---|
| 生成模型 | DeepSeek 配置模型，结构化调用使用 `disable_thinking=True` | 实际服务端模型 ID、调用日期和响应版本 |
| Embedding | `BAAI/bge-m3` / 1024 维 | 实际服务版本、digest、采集日期 |
| Reranker | `BAAI/bge-reranker-v2-m3` | 实际服务版本和调用记录 |
| Gap Board | `research-dataset-qwen3:run7-q8-templatefix`，用于垂类抽取/标注 | 模型 digest、服务器运行记录、隧道状态 |
| 外部检索 | Semantic Scholar，结果区分实时、缓存、部分成功和失败 | Demo 日期的 API 状态、授权和快照记录 |
| 基础设施 | PostgreSQL 15、Milvus 2.4、Redis 7、Celery 5 | staging 实际版本与 `/health/ready` 输出 |

准确产品口径：GapMind 使用通用生成模型完成受控问答和草稿生成，使用 BGE 检索证据，使用 `research-dataset-qwen3` 作为研究空白抽取/标注组件，并通过 Evidence Passport、Critic、Evidence Gate 和 HITL 限制模型输出。

## 4. 数据与材料冻结状态

| 资产 | 当前状态 | 能否作为最终效果证据 |
|---|---|---|
| Demo 资料 | 已建立知识源台账和快照 manifest 模板，授权资料/哈希尚未补齐 | 否 |
| Chat Gold | 已有 5 题样本和人工记录；目标冻结 12—20 题 | 否，当前仅能说明样本机制 |
| Retrieval Gold | 已有 gate baseline；similar 维度为 0.6667，整体 gate 未通过 | 可作为失败/基线案例，不能包装成整体通过 |
| 严格 A/B | 当前 facet Gold 标记 `experiment_usable=false`，尚未同题同快照完成 | 否 |
| 用户测试 | 脚本已建立，真实用户和脱敏记录尚未完成 | 否 |
| 三分钟 Demo | 脚本骨架已建立，冻结环境、三轮彩排和录屏尚未完成 | 否 |

## 5. 提交包当前状态

`submission/` 已被 `.gitignore` 排除，当前仅作为本地工作副本：

- PPT：`submission/04_作品方案_v1.pptx`（由 `GapMind_作品方案_v1.pptx` 生成的编号工作副本，内容仍为 v1）；
- 01—03、05—07 材料骨架；
- `submission/demo/three_minute_demo_script.md`；
- `submission/reproducibility/README.md`、`model_manifest.md`、`data_manifest.md`、`smoke_test.md`、`smoke_test.ps1`。

提交前必须补齐 04 编号 PPT 的最终内容/版本、参赛信息、正式 Demo 地址、授权知识快照、效果数据、用户授权/脱敏记录、模型和数据哈希，并删除所有 `pending`、真实密钥和未经授权材料。

## 6. 最终冻结门槛

- [ ] 用户审查工作区并授权最终 commit；
- [ ] 在 staging 执行 0025/0026/0027/0028 迁移和健康检查；
- [ ] 两个真实 token 完成 Workspace/论文/产物/任务/Chat 越权测试；
- [ ] 授权资料快照、12—20 题 Gold、严格 A/B 和人工复核完成；
- [ ] 两名真实用户完成同一套测试并脱敏；
- [ ] 三轮 Demo 彩排、故障演练和最终录屏完成；
- [ ] 干净环境 Smoke Test 和提交包完整回归完成；
- [ ] 形成最终 commit 后重新生成本清单和 checksums。
