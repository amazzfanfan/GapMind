# 0809 交付说明（W0/W1/W2/W5/W7 代码层完成）

> 日期：2026-08-09
> 作者：yx（分支 `yx_dev`）
> 关联：`research_assistant_completion_plan.md`（当前计划，§8 TODO 已同步更新）
> 命名约定：**本文档起，docs/ 新增文档一律以 `MMDD_` 日期开头命名**

---

## 一、本次交付概述

按计划文档推进，2026-08-09 完成 5 个工作流的**代码层实现**并全部推送 origin：

| Commit | 工作流 | 核心能力 | 测试 |
|---|---|---|---|
| `47ed9f7` | **W0 研究准备度** | 五维 readiness + 前端进度条 + 单一来源计数 | +13 |
| `8824e7b` | **W1 外部全文核验** | URL 规范化 + 全文角色重判 + 失败路径 | +10 |
| `4536e4b` | **W2 机会质量** | Critic 反馈注入 Opportunity prompt + 审计字段 | +6 |
| `b87ab1a` | **W7 全生命周期 agent** | Analyze/Write/Respond + 前端入口 | +5 |
| `c229151` | **W5 端到端/降级** | HITL 4 决策 + Timeline + 幂等 + 降级 | +9 |

**测试基线：363 后端（320 → +43）+ 26 前端 vitest + tsc 通过。**

---

## 二、交付清单

### W0 — 研究准备度与下一步（zwx P0-1）✅

- **后端**：`backend/app/domains/workspace/readiness.py`
  - `WorkspaceReadinessService`：corpus/retrieval/knowledge/discover/research 五维，每维 `ready/waiting/blocked` 三态 + `blocking_actions`（"为何 + 去哪"）+ `recommended_next_action`（单一来源；research 不阻塞循环，HITL 审核知识/机会优先）
  - `GET /workspaces/{id}/readiness` 端点（`workspace/router.py` + `schemas.py`）
- **前端**：`components/WorkspaceReadinessCard.tsx` 六步进度条（文献→知识→发现→确认→计划→执行）；Overview/Dashboard 统计改用 `readiness.counts`（修复原 `items.length` 被分页截断导致的数量不一致），Dashboard 每 workspace 5 并发计数请求减为 1 个
- 测试：`tests/test_workspace_readiness.py`（13）

### W1 — 外部全文核验闭环（代码层）⏳ 真实 OA 端到端待环境

- `_normalize_pdf_url`（`discover/service.py`）：S2 偶发 `http://`/`//` 前缀 URL → https、`arxiv.org/abs/` → `pdf/`，避免 `download_pdf` 强要求 https 导致 import_failed
- `_judge_external_fulltext_roles`：pipeline ready 后读论文**全文**（非 metadata）LLM 重判角色，幂等（snapshot `fulltext_role_judged`）+ LLM 失败降级保留 metadata 角色；挂 execute_run `elif verified:` 分支（resume 恢复时触发）
- 失败路径：import_failed / no_pdf / verification_failed（pipeline failed）全测试覆盖
- 测试：`tests/test_discover_fulltext.py`（10）
- **剩余**：W1-1/2/7（真实 OA 下载→parse→extract→硬门槛）待环境

### W2 — 机会生成多候选质量（代码层）⏳ 真实跑待环境

- `_critic_challenges`：从 narrow/reject 判定收集挑战（去重 ≤3）
- `_synthesize_candidates` 新增 `critic_feedback` prompt 约束：挑战作为 `CRITIC_FEEDBACK` 注入，要求提案**明确回应**批评者缺口
- execute_run：Critic 有挑战 → 第二轮综合（带约束）→ 与首轮按 title 去重合并，新候选标记 `critic_refined`（实现计划 3.3 "收窄：换角度重试"）
- 审计字段：`DISCOVER_PROMPT_VERSION="discover-v2"` + `_corpus_snapshot`（`workspace-v1-Np-Mk` 指纹，create_run + preflight 刷新）
- 测试：`tests/test_discover_quality.py`（6）
- **剩余**：W2-1/5（真实跑 1-3 次看多候选区分度）待环境

### W7 — 全生命周期 agent（代码层）⏳ 真实 LLM 一条链待环境

- 3 个受控 agent（`agent/service.py`，复用 AgentRun/Step/Artifact，`succeeded` 终态 + [En] 回链，零迁移）：
  - **AnalyzeAgent**：实验 JSON（手动数据）→ 对照证伪标准 → verdict（支持/部分支持/否定/证据不足）+ `research_memo.md`
  - **WriteAgent**：计划+证据 → `paper_draft.md` 章节草稿（Abstract/Intro/Method/Experiments/Conclusion）
  - **RespondAgent**：`reviewer_comments` → `rebuttal.md` 逐条回复 + 依据回链
- 前端：ChatComposer 加 3 mode + plan Select；ChatPage input 组装（respond 自动用 prompt 作 reviewer_comments）；ChatAgentRunCard 多态渲染 md 产物；`agent_type` Literal 扩展（后端 + 前端 + gen:api）
- 测试：`tests/test_agent_lifecycle.py`（5）
- **剩余**：W7-5（真实确认计划→模拟实验→分析→写作→回复一条链）待环境

### W5 — 端到端验收 + 失败降级（代码层）⏳ 真实环境端到端待做

- HITL 4 决策 × API 测试 + Timeline/HumanDecision 追溯：`tests/test_discover_hitl.py`（5）
- 修复真实 bug：`HumanDecision.created_at` / `OpportunityVersion.created_at` 的 `server_default="now()"` 在 SQLite 测试环境存字面量导致读取报错 → 加 Python 侧 default（`_now_utc`，schema 不变）
- 降级/幂等：`tests/test_discover_resilience.py`（4）——execute_run terminal 幂等、synthesis LLM 失败降级 rule_based_fallback
- 四类降级（S2 429 / LLM / Milvus / PDF）已有覆盖（external_queries / _BoomLLM / retrieval_lifecycle / fulltext）
- **剩余**：W5-7（真实环境正常 + 降级走查）待环境

---

## 三、当前系统能力（对照计划 §2 验收清单）

| 验收项 | 状态 |
|---|---|
| 导入→解析→抽取→证据回链 | ✅ 已能 |
| Workspace 检索三合一 + RAG 对话 | ✅ 已能 |
| 多智能体协同（MA：Planner/Critic/收窄 + AgentStep 交接流）| ✅ 已能（此前完成）|
| 外部全文核验（metadata + 全文）| ⏳ 代码层就绪，真实端到端待环境 |
| 多候选机会 + 证据门 + 收窄/否定 | ✅ 代码层就绪（W2）|
| HITL 4 决策 + Timeline | ✅ 已能 + 测试（W5）|
| 研究计划 / 代码生成 / 分析 / 写作 / 审稿回复 | ✅ 代码层就绪（W7）|
| 研究准备度 + 证据可信度卡片 | ✅ 已能（W0 + W3）|
| 降级路径 | ✅ 测试层覆盖（W5）|

## 四、剩余工作（诚实缺口）

| 项 | 依赖 | 状态 |
|---|---|---|
| **真实环境端到端验收**（W1-1/2/7、W2-1/5、W5-7、W7-5）| Celery worker + S2 API + 网络 + 真实 LLM | 待做 |
| **W6 封版 + 演示预演** | 真实环境 | 未开始 |
| **MA-1 拆分 DiscoverService**（~2000 行维护重构）| 无（纯代码）| 未开始 |
| 检索质量 Gate（similar 0.778 / counter 0.667）| 性能优化已搁置 | demo 作 baseline |
| 外部自动生成 recall 0.286 | 管线已验证 | demo 作辅助线索 |

## 五、Git 状态

- 分支 `yx_dev`：5 个 commit（W0/W1/W2/W7/W5）已 push origin，工作树干净

## 六、命名约定（2026-08-09 起）

- **docs/ 新增文档一律以 `MMDD_` 日期开头命名**（如 `0809_delivery.md`），后接简短描述
- 交接/交付类：`MMDD_delivery.md` / `MMDD_handoff.md`
- 已存在的非日期命名文档暂不强制改名，新写文档遵守本约定
