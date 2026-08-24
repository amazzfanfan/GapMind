# GapMind P0 完成审计与收尾清单

**审计日期**：2026-08-25
**分支**：`yx_dev`
**审计对象**：`docs/0824_competition_todolist.md` 中 T0—T5 及 GATE-0
**审计原则**：代码测试、模板存在和真实比赛证据分开记录；没有真实资料、人工判定、用户记录、staging 输出或录屏时，不标记为已完成。

## 一、结论

当前候选版本已经完成较大部分代码级安全、可靠性和交付骨架工作，但尚未通过 GATE-0，因此 P0 不能标记为完成。

当前最重要的未闭环项不是新增功能，而是：

1. 授权且可复现的 Demo 知识快照；
2. 12—20 题冻结 Gold、严格同题 A/B 和人工复核；
3. 两名真实目标用户的结构化试用记录；
4. staging PostgreSQL 迁移、双 token 越权和依赖故障演练；
5. 三轮三分钟 Demo 彩排、录屏和最终 Smoke Test；
6. 用户填写参赛信息、正式地址、授权/许可证、最终 commit 和提交包校验值。

这些证据不能由 AI 代填，也不能由自动化测试推断。

## 二、按任务的当前证据状态

| 任务 | 当前判定 | 已有证据 | 仍缺的验收证据 |
|---|---|---|---|
| T0-01 看板 | 已完成 | `docs/0824_competition_delivery_board.md` | 最终冻结时更新状态即可 |
| T0-02 基线 | 已完成（历史基线） | `docs/0824_baseline_manifest.md`、候选版本清单 | 最终 commit 后重做一次 |
| T0-03 不做事项 | 已完成 | `docs/0824_scope_and_claims.md` | 现场材料继续遵守 |
| T0-04 入口一致性 | 代码/文档首轮完成 | `docs/0824_entry_and_material_consistency_audit.md` | 最终链接、快照、回归和提交包复核 |
| T1-01—T1-03 定位、Persona、核心任务 | 已完成 | `docs/0824_domain_positioning.md`、`docs/0824_personas_and_tasks.md`、`docs/0824_core_demo_tasks.md` | 非开发者复述验证仍可补强 |
| T1-04 对外话术 | 进行中 | README、首页、PPT v1（两份工作副本已更新为 481 tests）、话术草案、Demo 脚本 | 正式地址、真实效果页、视频字幕/录屏和现场话术最终复核 |
| T2-01 模型服务清单 | 代码口径已记录 | `docs/0824_model_manifest.md`、`docs/0824_model_card.md` | 实际运行时 ID、digest、调用日期、授权快照 |
| T2-02 垂类模型口径 | 口径已冻结，证据未齐 | 模型卡明确“垂类抽取/标注组件 + 通用生成模型 + 证据工作流” | Gap Board digest、训练/数据证明和对照实验 |
| T2-03 知识源台账 | 模板完成 | `docs/0824_knowledge_source_registry.md` | 每份 Demo/Gold 资料的许可、哈希、获取日期和远程发送许可 |
| T2-04 知识库快照 | 结构完成，快照未冻结 | `docs/0824_knowledge_snapshot_manifest.md`、`submission/reproducibility/data_manifest.md` | 授权脱敏资料、索引导出、恢复演练和哈希 |
| T2-05 导入质量反馈 | 代码级完成 | 分块上传、PDF magic、50 MB 上限、Workspace 配额、解析质量字段、前端状态和测试 | 真实 PDF、恶意样本/网关扫描、staging 磁盘与恢复验证 |
| T2-06 Gold 题集 | 草案机制完成 | `docs/0824_gold_evaluation_plan.md`、当前 5 题样本 | 冻结 12—20 题；标准答案和来源不能由系统输出反向修改 |
| T2-07 基线/A-B | 机械基线完成（离线评测器已复核） | `docs/0824_baseline_ab_report.md`、Retrieval Gate 报告 | 当前候选同快照同题 A/B、人工正确性、至少 3 个目标问题的可解释改进 |
| T2-08 人工审查 | 5 题登记完成 | `docs/0824_manual_review_register.md` | 冻结 Gold 盲评、引用支持判断、拒答判断和修复后案例 |
| T3-01 真实用户 | 未完成 | 用户测试条件和脚本已准备 | 两名符合 Persona 的用户、授权和测试安排 |
| T3-02 用户试用脚本 | 文档完成 | `docs/0824_user_test_script.md` | 按真实用户执行并留存脱敏记录 |
| T3-03 用户测试 | 未完成 | 无 | 两名用户的同一套任务、计时、反馈和授权记录 |
| T3-04 三分钟脚本 | 脚本完成 | `submission/demo/three_minute_demo_script.md`、`docs/0824_three_minute_demo_checklist.md` | 冻结 Workspace、实时/缓存标记和现场操作实证 |
| T3-05 Demo 冻结环境 | 未完成 | 复现/快照结构已定义 | 可恢复数据包、离线 fallback、服务状态表 |
| T3-06 三轮彩排 | 未完成 | 检查清单已准备 | 三轮计时记录、失败演练、录屏和校验值 |
| T3-07 效果报告 | 模板完成 | `submission/06_效果验证报告.md`、效果报告模板 | Gold、用户、Demo 和系统指标实际填充 |
| T4-01 合规声明 | 草案完成 | `submission/02_伦理与安全合规声明.md` | 授权、脱敏、负责人确认和日期 |
| T4-02 认证/ACL | 代码级完成，环境未验收 | Bearer、owner scope、迁移 `0025`/`0027`/`0028`、`docs/0825_acl_route_audit.md` | staging PostgreSQL、两个真实 token、跨资源矩阵和日志检查 |
| T4-03 数据分类/远程调用 | 文档完成 | `docs/0824_data_classification_and_remote_calls.md` | 用冻结资料实际核对远程发送边界和日志 |
| T4-04 AI/人工状态 | 代码/规范完成（新鲜度和 ZIP 状态清单已补） | `docs/0825_ai_human_status_spec.md`、Chat/Discover/Agent UI 标识、`EvidenceManifest.evidence_freshness`、`ARTIFACT_STATUS.json` | 端到端截图、导出文件和用户可理解性验证 |
| T4-05 健康检查 | 代码级完成 | `/health`、`/health/ready`、定向测试 | staging 输出和依赖故障现场演练 |
| T4-06 配置/上传安全 | 代码级完成，生产未验收 | CORS、Bearer、上传边界、配额和质量字段 | 生产 secret、CORS 预检、恶意样本、磁盘权限和备份恢复 |
| T4-07 降级矩阵 | 文档完成 | `docs/0824_dependency_state_matrix.md` | DB/Redis/Milvus/LLM/worker/S2 逐项断依赖演练 |
| T5-01 提交材料目录 | 工作副本已建立 | `submission/README.md`、01—07、Demo、reproducibility | 用户填写和最终材料审核 |
| T5-02 版本冻结 | 候选清单完成 | `docs/0825_candidate_release_manifest.md`，候选 head `0028_search_acl` | 最终 commit、运行时版本、模型/数据/Prompt 哈希 |
| T5-03 复现手册 | 文档完成 | `submission/reproducibility/README.md` | 另一环境按手册实际恢复 |
| T5-04 Smoke Test | 脚本/说明完成 | `submission/reproducibility/smoke_test.ps1`、`smoke_test.md` | staging 执行；当前脚本支持 `-RequireAuth`、双 token Workspace/Chat 基础检查 |
| T5-05 最终回归 | 未完成 | 候选回归模板、`submission/reproducibility/release_gate.ps1` | 冻结环境全量回归、Smoke、材料、Gold 数量、SHA-256/digest 和 checksum；当前 Gate 预期因占位符和脏工作区失败 |

## 三、当前自动化证据

以下结果只证明代码级健康，不证明真实用户效果、数据授权或 staging 可用性：

| 检查 | 最近结果 |
|---|---|
| 后端全量测试 | `481 passed, 2 warnings` |
| 前端测试 | `17 files / 56 passed` |
| TypeScript | 通过 |
| 前端生产构建 | 通过；主包约 1.83 MB，存在 Vite chunk warning |
| ESLint | `0 errors / 14 warnings` |
| Python compileall | 通过 |
| Alembic heads | `0028_search_acl (head)` |
| Smoke 脚本语法 | `SMOKE_SCRIPT_PARSE_OK` |
| Git 空白检查 | 无 whitespace error；保留换行符转换提示 |

### 环境可用性复核（2026-08-25）

- 本机 `8000/5173/5432/6379/19530/11434` 均未监听，无法执行真实 API Smoke、PostgreSQL 迁移、双 token 越权或依赖故障演练。
- Docker Engine named pipe 返回权限错误，不能把 Compose 启动或容器内验证写成已完成。
- 已将 `submission/reproducibility/smoke_test.ps1` 补为可在 staging 使用 `-RequireAuth` 的双 token 脚本；当前仅完成 PowerShell 语法解析，未完成真实执行。

## 四、GATE-0 判定

当前 GATE-0：**未通过**。

尚未满足的硬条件：

- 尚无 12—20 题冻结 Gold 和至少 3 题完整人工标准答案/判定；
- 尚无两名真实目标用户的同套任务证据；
- 尚无冻结资料和可恢复 Demo Workspace；
- 尚无三分钟 Demo 三轮彩排和录屏；
- 尚无 staging PostgreSQL 迁移、双 token 和依赖故障演练记录；
- 提交包仍含 `pending/待填写/待冻结` 字段；
- 尚未获得最终 commit 授权，也没有最终 checksum。

## 五、下一次可执行顺序

当用户提供真实材料或 staging 条件后，按以下顺序执行：

1. 录入授权知识源和资料哈希，导入最小快照并生成 `data_manifest`；
2. 将 Gold 扩展到 12—20 题，冻结标准答案，运行同题 A/B，完成盲评；
3. 以两个真实用户执行 `docs/0824_user_test_script.md`，脱敏并填效果报告；
4. 在 PostgreSQL staging 执行迁移 `0025`—`0028`，运行 `smoke_test.ps1 -CreateWorkspace` 配合两个 token；
5. 固定 Demo 的实时/缓存边界，完成三轮彩排、录屏和失败演练；
6. 填充 01—07、模型/数据清单，运行最终回归和 checksum；
7. 用户审查工作区并明确授权 commit 后，再执行精确路径提交。

## 六、禁止提前宣称

- 不能把当前 5 题 draft Gold 当作完整效果评测；
- 不能把 481 个自动化测试当作真实用户认可或科学正确性；
- 不能把本地模型配置和代码口径当作已冻结的服务 digest；
- 不能把本地 ACL 定向测试当作生产多租户隔离证明；
- 不能把 Demo 脚本或缓存结果当作已完成的实时三分钟演示。
