# GapMind 任务清单与 ChatGPT 交接（2026-08-20）

> 本项目已完成大量工作。此文档第一部分是新任务清单（含历史已完成项的归档），
> 第二部分是**给 ChatGPT 的交接说明**——如果要让一个新的 AI 会话接手后续开发，请把它连同仓库一起提供。

---

## 第一部分：任务清单

### 当前未完成（按优先级）

| # | 任务 | 描述 | 状态 |
|---|---|---|---|
| T1 | **现场演示预演（W6-5 完整版）** | 代码生成 Phase A/B + 首页直达/推荐已上线，需按 0811_demo_script.md 重走一遍全流程（导入→对话→Discover→代码生成→分析→写作→审稿），确认演示动线最短 | ☐ |
| T2 | **前端回归验证** | 本批 3 处改动（LifecycleModules 直达 / ChatPage ?mode= / Dashboard 推荐聚合）+ 暗色主题，浏览器两主题走查一遍 | ☐ |
| T3 | **部署到 3090 服务器** | 按 `deploy/README.md`（本地物料，不入库）：compose 端口已加固、nginx/systemd/Dockerfile 已备好；部署后按手册"首跑自检"7 项验证 | ☐ |
| T4 | **S2 演示前确认** | 当前网络下 S2 SSL 偶发失败（推荐接口 502）——演示时若 S2 不通，推荐卡自动隐藏（graceful），但 Discover 外部核验会降级；演示前确认 S2 可用或准备降级话术 | ☐ |
| T5 | **README 部署段核对** | deploy/ 不入库，README 的 Deployment 段已删；确认无死链 | ✅ 已完成 |

### 历史已完成（归档）

- **代码生成 Phase A**（已提交 `71080c5`）：蓝图→逐文件生成→静态检查（含 syntax_valid）→rubric 覆盖度自检→known_gaps→evidence_refs；详见 `0819_code_generation_improvement.md`
- **代码生成 Phase B**（已提交 `21d7338` + `1563948`）：CodeRAG-lite 分面检索、单文件失败降级（file_errors）、产物下载（RFC 5987 + X-File-Name）、ZIP 含 RESEARCH_PLAN.md、移除 Docker 沙箱（决策记录见文档 §十）
- **LLM 主备降级**（已提交 `a03c397`）：DEEPSEEK_BACKUP_* 三项全填启用，主失败自动切备用
- **环境文件整合**（已提交 `a03c397`）：三份 .env.example 合并为根目录一份；config 按文件位置解析根 .env（不依赖 CWD）；vite envDir
- **首页科研生命周期直达 + 推荐聚合**（已提交 `0ae9173`）：阶段直达（?mode=）+ 首页论文推荐卡
- 早期归档见 `0811_todolist.md`（P0/P0.5/P1 全部完成）

### 明确不做（维持）
- P2-4 外部自动生成 recall：校准完成，不再推进（gold set 过拟合）
- 登录系统：不必要（X-User-ID 已是认证扩展点，赛后接 OIDC 即可）
- 多模型 provider 管理：不必要（网关天然多厂商，主备降级已够）
- 沙箱（代码执行验证）：已移除

---

## 第二部分：给 ChatGPT 的交接说明

> 如果你正在用 ChatGPT 接手本项目的后续开发，请把以下内容作为上下文的一部分提供给它。
> 仓库：`https://github.com/yuanxing629/GapMind`（分支 `yx_dev`）

### 0. 一句话
GapMind 是一个面向 AI/CS 研究者的 **Human-in-the-Loop AI Research Workspace**（比赛项目，**近封版**）：导入论文 → 抽取知识 → 语义检索 + 多智能体 Discover 发现研究机会（含 Critic 与外部新颖性核验）→ 用户确认 → 研究计划 → 代码生成 → 结果分析 → 论文写作 → 审稿回复，另有研究空白棋盘（zf 微调模型）与 Workspace RAG 对话。

### 1. 必读文件（按序）
1. `AGENTS.md` —— 项目记忆文件（中文），含目录结构、技术栈、核心工作流、启动命令、**关键约定**（HITL 铁律、Evidence Passport、软删除、提交纪律等）、常见坑。**最重要，先读。**
2. `docs/0811_todolist.md` —— 历史任务清单（大部分已完成，看"状态"列即可）
3. `docs/0819_code_generation_improvement.md` —— 代码生成改进的调研 + Phase A/B 实施记录 + 决策记录（为什么砍沙箱）
4. `docs/0814_independent_modules_plan.md` / `docs/0814_changes_summary.md` —— 独立模式模块化设计
5. `docs/0818_dark_theme_fix_plan.md` —— 暗色主题修复（含实施记录）
6. `docs/0811_demo_script.md` —— 现场演示脚本

### 2. 启动（本地开发）
```bash
cd infra && docker compose --env-file ../.env up -d   # postgres/redis/milvus
cd backend && .venv\Scripts\activate
alembic upgrade head
uvicorn app.main:app --reload --port 8000
# 另开终端
celery -A app.workers.celery_app worker --loglevel=info   # Windows 自动 solo 池
cd frontend && npm install && npm run dev                # :5173
```
- `.env` 在**仓库根目录**（单一环境文件，后端/compose/vite 共用），从根 `.env.example` 复制
- 测试：`cd backend && .venv/Scripts/python.exe -m pytest tests/ -q`（407 个）+ `cd frontend && npm test -- --run`（43 个）+ `npx tsc --noEmit`
- Windows 下 `backend/.env` 的系统环境变量会覆盖 `.env`，API key 不生效先 `unset`

### 3. 关键约定（违反会被打回）
- **提交纪律**：改完代码 → 跑测试 → **汇报，等用户明确告知才 commit**；push 需用户单独指示。**绝不自行 commit/push。**
- **HITL 铁律**：AI 只出候选，关键资产（研究计划等）必须人工确认才落正式表
- **软删除从不硬删除**；数据按 workspace_id 隔离
- **LLM 调用一律 `disable_thinking=True`**（勿同时传 `reasoning_effort`，会 400）；主备降级已内置（`DEEPSEEK_BACKUP_*`）
- **OpenAPI → TS 类型自动生成**（`npm run gen:api`），`api.gen.ts` 勿手写
- **Celery Windows 用 solo 池**；任务修改后必须重启 worker
- **docs/ 新文档以 `MMDD_` 开头**；交付/交接类用 `MMDD_delivery.md` / `MMDD_handoff.md`
- **zf 模型**（Gap Board）经 SSH 隧道 `127.0.0.1:11434` 访问；本机不要装本地 Ollama 遮蔽隧道
- 沙箱/代码执行验证已移除，不要重新引入（决策记录见 0819 文档 §十）

### 4. 代码生成 Agent 现状（最容易改坏的地方）
- 流水线：workspace_retrieval（CodeRAG-lite 分面检索）→ module_design（蓝图 JSON）→ code_generation（逐文件，AST 接口摘要）→ static_review（纯 Python 5 项+语法门）→ rubric_check（覆盖度自检，产出 code_rubric.md + known_gaps）→ artifacts_ready
- **单文件失败降级**：某文件重试两次仍失败 → 跳过并记 `file_errors`，run 不炸（这是对"模型偶发非 JSON"的兜底）
- 代码在 `backend/app/domains/agent/service.py`（较大，约 2000 行，未拆分）
- 相关测试：`tests/test_agent_api.py`（含多调用 FakeGateway）、`tests/test_llm_fallback.py`

### 5. 当前未完成任务（见本文件第一部分）
- T1 现场演示预演（按 demo_script 走全流程）
- T2 前端回归验证（本批 3 处改动 + 暗色主题）
- T3 部署到 3090 服务器（deploy/README.md 是本地物料，不入库）
- T4 S2 演示前确认（当前网络 S2 SSL 偶发失败，推荐接口 502——已做 graceful 容错）

### 6. 本会话最近改了什么（供 ChatGPT 快速了解，勿回滚）
- 代码生成 Phase A/B（蓝图/逐文件/静态检查/rubric/known_gaps/下载/ZIP 含计划/移除沙箱）
- 首页：LifecycleModules 阶段直达（`?mode=`）+ 论文推荐聚合卡（解耦加载）
- LLM 主备降级；环境文件整合到仓库根；compose 端口绑定 127.0.0.1
- 暗色主题写死颜色修复（提交 `fb5cdb9`）；对话流式输出修复（P0.5-1）
- 最近提交：`0ae9173`（首页直达+推荐）→ `a03c397`（主备降级+env 整合）→ `21d7338`/`1563948`（Phase B）→ `71080c5`（Phase A）→ `fb5cdb9`（暗色）

### 7. 常用命令与地址
- API 文档 http://localhost:8000/docs · API 基路径 http://localhost:8000/api/v1 · 前端 http://localhost:5173
- 后端目录 `D:\MyCode\Spark-competition\refactor\GapMind\backend` · 分支 `yx_dev` · 项目仓库 https://github.com/yuanxing629/GapMind
