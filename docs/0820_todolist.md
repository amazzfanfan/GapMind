# GapMind 本地封版收尾清单与交接（2026-08-22）

> 当前策略：先完成本地功能闭环、异常降级和演示稳定性，再考虑 3090 部署。
> 服务器部署暂不执行，也不作为本地封版的前置条件。

## 一、当前状态

GapMind 的主链路已经完成：论文导入与解析、知识抽取、检索与 Workspace RAG、Discover 多智能体、外部新颖性核验、Critic、Evidence Passport、HITL 四决策、研究计划、代码生成、结果分析、论文写作、审稿回复，以及研究空白棋盘均已具备。

最近一次本地验证结果：

- 后端：`408 passed`
- 前端：`48 passed`
- TypeScript 类型检查：通过
- 前端生产构建：通过
- 浏览器走查：首页、亮暗主题、推荐聚合、知识图谱、Discover、HITL、研究计划、代码生成、W7 独立模式均可加载
- 本地工作区：主 Demo workspace 为 `123100ea-e75b-4110-9048-1f5b92668c32`
- Alembic：`0018_paper_recommendations (head)`；Celery 本机 worker 可响应 `ping`

本地未提交的修复包括：Workspace RAG 检索失败时通过 SSE 返回明确错误、前端停止无限“正在思考”并显示重试入口，以及对应后端测试。遵守提交纪律，未经用户明确指示不得 commit/push。

## 二、剩余工作（按优先级）

### P0：本地演示稳定性

| 编号 | 工作项 | 完成标准 | 状态 |
|---|---|---|---|
| L1 | 外部 embedding 失败降级 | 流式 RAG 检索失败会结束 loading、持久化失败状态并显示向量化/Milvus 恢复提示与重试入口；无证据时不伪造答案 | ✅ 2026-08-22 |
| L2 | Semantic Scholar 降级体验 | 429、超时、服务不可用显示稳定中文提示；缓存推荐可继续展示并标识 stale；首页推荐按 workspace 渐进加载，不等待冷源 S2 请求 | ✅ 2026-08-22 |
| L3 | Demo workspace 状态清理 | 已定位 44 条历史失败任务（旧 Ollama 404、早期 LLM/烟雾测试等）；不删审计记录，首页/概览仅提示 24 小时内的失败，历史记录留在处理中心 | ✅ 2026-08-22 |
| L4 | 演示脚本最终回归 | 已完成首页、知识图谱、Discover 交接/外部候选、HITL、研究计划、独立模式烟雾回归；仍需按 `docs/0811_demo_script.md` 做一次不间断全流程预演并固化备用话术 | ◐ |
| L5 | 本地启动与健康检查 | 已确认 `health/ready`、Demo readiness、Alembic head 和 Celery worker ping；后端/前端服务可用 | ✅ 2026-08-22 |

### P1：功能边界与用户体验

| 编号 | 工作项 | 完成标准 | 状态 |
|---|---|---|---|
| F1 | W7 独立模式回归 | `analyze`、`write`、`respond` 无 workspace 时可独立运行；必须研究计划的模式给出正确提示，不出现跨 workspace 误用 | ☐ |
| F2 | Gap Board 边界回归 | Ollama SSH 隧道可用、不可用、超时时均有明确状态；棋盘筛选、高亮、候选交接 Discover 的行为一致 | ☐ |
| F3 | HITL 与证据约束复核 | 未确认的机会不能生成正式研究计划；确认、编辑确认、拒绝、暂缓均写入 Timeline，版本与 Evidence Passport 可追溯 | ☐ |
| F4 | 任务状态体验 | parse/extract/discover/agent 任务的失败、重试、取消和重派发状态在前端一致展示；Celery Windows solo 池重启说明补齐 | ☐ |
| F5 | 前端错误与空状态 | 统一处理 API 错误格式、网络断开、空工作区、无证据、过期缓存和长文本；亮暗主题下均无不可读文字或按钮 | ☐ |

### P2：质量、文档与工程收尾

| 编号 | 工作项 | 完成标准 | 状态 |
|---|---|---|---|
| Q1 | 外部服务失败测试 | 为 embedding、Semantic Scholar、LLM 主备切换、流式错误和缓存 stale 增加不依赖外部服务的测试 | ☐ |
| Q2 | 完整回归基线 | 后端 pytest、前端测试、`tsc --noEmit`、生产构建全部通过；后端 API 变更后执行 `npm run gen:api` | ☐ |
| Q3 | lint 工具修复 | 补齐或确认 ESLint 9 配置，使 `npm run lint` 可执行；若暂不修复，记录原因和替代检查方式 | ☐ |
| Q4 | 文档引用整理 | 处理 `docs/0811_demo_script.md` 对缺失历史文档的引用；补充本轮收尾记录、已知风险和演示注意事项 | ☐ |
| Q5 | 数据与迁移检查 | 确认 Alembic head、软删除过滤、workspace 隔离、关键索引和幂等任务行为；不得通过改固定 Gold Set 绕过评测 | ☐ |

## 三、暂缓事项

### T3：3090 部署

暂不执行。待本地 P0/P1 完成、演示回归稳定后，再根据 `deploy/README.md` 进行部署和 7 项首跑自检。届时需要用户另行提供服务器 SSH 地址、端口、用户名、部署路径和认证方式。

## 四、已完成事项归档

- 基础链路：workspace、论文、PDF 解析、知识抽取、检索、Workspace RAG 对话
- 检索质量 Gate：semantic 1.0 / similar 0.889 / counter 0.833 / leakage 0
- Discover：Planner → Evidence → ExternalNovelty → Critic → Gate，AgentStep 交接流可见
- Evidence Passport、外部核验部分成功、HITL 四决策、不可变版本、Timeline 中文事件
- 研究计划、代码生成预览/下载、结果分析、论文写作、审稿回复
- 独立模式：`GET /workspaces/independent` 及 W7 独立入口
- 首页六生命周期模块、阶段直达、推荐聚合、亮暗主题
- 语义去重 feature flag、知识图谱去冗余、证据折叠、公式渲染、棋盘高亮
- gap 抽取幂等、棋盘矩阵类型筛选、Celery retry/cancel 重派发
- 本地前后端自动化测试与浏览器回归

## 五、已知风险

1. 当前环境的 SiliconFlow embedding 请求可能出现 `Connection error`，因此真实 Workspace RAG 不能作为离线测试前置条件。
2. Semantic Scholar 可能返回 HTTP 429，或因本机网络权限报 `WinError 10013`；演示不得依赖临时实时刷新。
3. Demo workspace 有 44 条历史失败任务，主要源于旧 Ollama 隧道 404、早期 LLM 重试和烟雾测试；概览只提示近期失败，完整审计仍在处理中心。
4. `npm run lint` 当前因缺少 ESLint 9 配置无法执行。
5. `docs/0811_demo_script.md` 引用了当前仓库不存在的 `0809_freeze_version.md` 和 `0811_e2e_results.md`。
6. zf 棋盘模型依赖服务器 Ollama SSH 隧道；本机不要启动 Ollama 占用 `127.0.0.1:11434`。

## 六、不可违反的项目约定

- LLM 调用一律 `disable_thinking=True`，不得同时传 `reasoning_effort`
- AI 只能产出候选；关键资产必须人工确认后才进入正式表
- 软删除，不硬删除；Task 由系统创建；Timeline 只读
- 数据按 `workspace_id` 隔离；检索文本进入 SQL 前必须移除 `\x00`
- 前端 API 类型由 `npm run gen:api` 生成，不手写 `api.gen.ts`
- 不引入微服务、K8s、图数据库或重型 Agent 框架
- 不自动执行 Agent 生成的完整代码，默认只预览/下载
- 改动完成并测试通过后先汇报，等待用户明确指示后才 commit；push 需单独授权

## 七、常用本地命令

```bash
# 基础设施
cd infra && docker compose --env-file ../.env up -d

# 后端
cd backend
.venv\\Scripts\\activate
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Celery（Windows）
celery -A app.workers.celery_app worker --loglevel=info --pool=solo

# 前端
cd frontend
npm run dev

# 回归
cd backend && .venv\\Scripts\\python.exe -m pytest tests/ -q
cd frontend && npm run test -- --run
npm run typecheck
npm run build
```

## 八、接手顺序

新会话接手时依次阅读：

1. `AGENTS.md`
2. 本文件
3. `docs/0811_demo_script.md`
4. `docs/0819_code_generation_improvement.md`
5. `docs/0814_independent_modules_plan.md`、`docs/0814_changes_summary.md`
6. `docs/0818_dark_theme_fix_plan.md`

默认从 P0 的 L1/L2 开始，先把外部服务不可用时的产品行为稳定下来，再处理 Demo 数据清理和完整演示回归。
