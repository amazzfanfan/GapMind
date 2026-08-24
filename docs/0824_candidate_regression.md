# GapMind 候选版本回归报告（模板）

**版本**：预冻结候选（2026-08-25）
**分支**：`yx_dev`
**状态**：代码级全量回归已执行；真实服务、用户、冻结资料和最终提交回归待执行。

## 1. 版本快照

| 项目 | 值 |
|---|---|
| commit | `07efdb7`（当前 P0 加固仍未提交） |
| Alembic head | `0028_search_acl` |
| Python/Node/npm | 运行时具体版本待补；命令环境已验证 |
| 数据 snapshot | 待冻结 |
| 模型 manifest | `docs/0824_model_manifest.md`、`docs/0825_candidate_release_manifest.md` |
| 执行时间 | 2026-08-24 至 2026-08-25，分项执行 |
| 执行人 | 项目负责人 |

## 2. 自动化结果

| 检查 | 命令 | 结果 | 备注 |
|---|---|---|---|
| 后端全量 | `cd backend; .venv/Scripts/python.exe -m pytest tests -q` | **481 passed, 2 warnings** | 代码级验证 |
| 前端测试 | `cd frontend; npm test -- --run` | **17 files / 56 passed** | Vitest |
| TypeScript | `cd frontend; npm run typecheck` | **通过** |  |
| 前端构建 | `cd frontend; npm run build` | **通过** | 主包约 1.83 MB 警告归入 P1 |
| ESLint | `cd frontend; npm run lint` | **0 errors / 14 warnings** | 警告需保留在限制说明 |
| OpenAPI 类型 | `cd frontend; npm run gen:api` | **通过** | 87 routes / 380922 bytes |
| Python 编译 | `backend/.venv/Scripts/python.exe -m compileall -q app alembic` | **通过** |  |
| Alembic head | `backend/.venv/Scripts/alembic.exe heads` | **`0028_search_acl`** | 通过；目标部署为 PostgreSQL 15 |
| Smoke Test | `submission/reproducibility/smoke_test.md` | 待执行 | 记录环境 |

说明：尝试用临时 SQLite 从零执行完整 Alembic 链时，在既有迁移 `0004_paper_parse_state` 的非 batch `ALTER` 处停止；这不是本轮 `0028_search_acl` 的执行结果。提交复现和 staging 仍应使用项目目标 PostgreSQL 15，并在该环境验证 `0025`—`0028`。

## 3. 业务路径

- [~] 新建 Workspace → 上传授权 PDF → 解析质量反馈（代码和定向测试通过，真实 PDF 待 staging）。
- [~] Chat 证据回答 → `[En]` 引用一致性 → 证据不足拒答（已有自动化覆盖，真实快照待验证）。
- [~] Discover → 支持/反证/外部核验 → Critic → HITL（单测/流程已有，外部服务现场演练待验证）。
- [~] 研究计划/代码草稿 → 人工确认 → 静态检查/下载（代码生成明确未执行，端到端截图待补）。
- [~] required 依赖故障 → `/health/ready` → 离线 fallback（健康检查已测，现场依赖矩阵待执行）。
- [ ] staging token → Workspace/Chat/Reading/Task/Knowledge/Timeline/搜索私有资源 owner 隔离 → 跨用户访问拒绝（需要 staging 两个真实 token和真实迁移）。

## 4. 未通过项处理

每个失败项必须记录：复现命令、错误输出、是否影响提交、临时规避、修复 commit 和重新验证结果。未完成或未验证不得在 PPT/报告中写成“已支持”。
