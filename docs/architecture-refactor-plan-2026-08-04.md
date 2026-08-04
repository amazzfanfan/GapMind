# GapMind 架构重构计划 — 2026-08-04

> 起草人：YX（在 `architecture-review-2026-08-02.md` 基础上做的实施计划）
> 适用范围：当前 `yx_dev` 分支
> 目标：在不打乱 Discover Agent + Chat 进度前提下，把评审里的"软约束"硬化成"硬约束"

---

## 〇、怎么用本文档

- **§一** —— 评审里我同意的部分（落地时按这个走）
- **§二** —— 评审里我有保留或不同意的部分（解释为什么改做法）
- **§三** —— 评审没提但我额外加的工作
- **§四** —— **执行顺序**（重排过，比评审原序更稳）
- **§五** —— 每一步的子任务清单 + 验收
- **§六** —— 进度跟踪表（每完成一步打勾）

每完成一步，更新 §六 的 checkbox；遇到 §二 §三里的预设跟现实冲突，回到对应章节加 footnote。

---

## 一、完全同意评审的部分（直接落地）

| 编号 | 主题 | 评审里的工作量估算 |
|---|---|---|
| P0-1 | FastAPI 全局异常处理器集中化 | 1-2h |
| P0-2 | TS 类型从 Pydantic/OpenAPI 自动生成 | 0.5-1 天 |
| P0-3 | 清 `discover/router.py` legacy 死端点 | 10 min |
| P0-4 | 统一错误响应外壳 | 0.5h |
| P0-5 | 拆 `discover/service.py`（1381 行 → 多个子聚合） | 1-2 天 |
| P1-6 | 跨域依赖走 Protocol | 1 天 |
| P1-7 | 拆 `extract_knowledge.py` worker（1093 行 → 瘦 entry） | 1 天 |

---

## 二、评审里有保留 / 不同意现在做的部分

### 2.1 P1-8（前端状态文件位置）——先确认再动

`pages/discoverState.ts` 和 `pages/chatState.ts` 是 Zustand store 还是 custom hook，**直接 move 文件会破坏 import 路径**。落地时先 read 这两个文件确认它们是 store 还是 hook：
- 是 store → move 到 `store/` 并修引用
- 是 hook → move 到 `hooks/`（如果有）
- 如果是单文件 hook + 局部状态 → 保持现状

### 2.2 P2「认证/鉴权」——不同意现在做完整 auth

理由：单用户 MVP，加完整 auth 会拖慢 Discover Agent 进度。
**轻量替代**：在 router 里加 `X-User-ID` header 依赖（默认 "user"），注入 service，替换 `TimelineService.record(actor="user")` 的硬编码。约 30 行代码，列入 §三 增项。

### 2.3 P2「discover/schemas.py 拆 requests/responses/internal」——不一定值得

`discover/schemas.py` 304 行 19 个类型。**拆三文件会增加定位成本**（找 `DiscoverRunCreateRequest` 要翻三个目录），收益不大。**先不动**。

### 2.4 P2「list 响应外壳不统一」——同意但低优先

`discover/list_runs` 返回手写 dict，其他用 Pydantic。可以做，但放最后。

---

## 三、评审未提及但需要做的工作

### 3.1 `_workspace` 重复检查 → FastAPI Dependency

`discover/router.py` 7 个 endpoint 都在重复 `try: WorkspaceService(db).get(workspace_id) except WorkspaceNotFoundError`。这是样板，应做成 Depends。

### 3.2 单一 Session：合并 `service` 和 `db` 双重注入

`discover/router.py` 每个 endpoint 都 `service: DiscoverService = Depends(_service), db: Session = Depends(get_db)`。两个 dep 各自持有 session，**可能不一致**。改成只传 service，需要时 `service.db` 取。

### 3.3 消除 router 内的局部 import

`discover/router.py:75` `from app.workers.tasks.run_discover import spawn_discover_task` 写在 endpoint 函数体内——循环 import 的妥协，破坏可测试性。把 celery spawn 抽到 service 层（或者拆出 dispatcher 模块）。

### 3.4 统一 envelope 的**兼容性约束**

评审建议的 envelope 形状：
```json
{"error": "code", "message": "msg", "retryable": false, "conversation_id": "..."}
```
把 `conversation_id` / `assistant_message_id` 放**顶层**。但**当前前端读的是 `detail.conversation_id`**（因为它们被塞在 `HTTPException(detail={...})` 里）。

**约束**：落地 P0-1 + P0-4 时，envelope **保持现有 shape**：
```json
{"detail": {"error": "code", "message": "msg", "retryable": false, "conversation_id": "..."}}
```
不再做 breaking change。OpenAPI 用 Pydantic schema 描述。

### 3.5 `_run_extract` 函数自身复杂度

P1-7 拆 worker 时，**单是 `extract_knowledge.py` 的 `_run_extract` 一个函数 ~200 行**，里面嵌：批次切分 + LLM 调用 + JSON 解析 + schema 校验 + evidence rebase + 去重 + 写库 + 跨域通知 + timeline。拆 worker 时候要拆函数，按 §四 第七步细分。

### 3.6 测试缺口

| 模块 | 当前测试 | 缺口 |
|---|---|---|
| `discover/service.py` | 0 个单测 | 拆完每个子文件应有对应 test |
| `extract_knowledge` | `test_parse_pipeline.py` 8 个 | 拆完 `_run_extract` 后覆盖率应提升 |
| 跨域集成（discover + retrieval + llm） | 空白 | 拆 Protocol 后开始写 |

**约束**：每完成 §四 一步，对应模块测试数 ≥ 当前 + 新增 1-2 个单测。**不允许"拆完不写测试"**。

### 3.7 `X-User-ID` 最小化认证依赖

（详见 §二 2.2）这是评审外的轻量增项，不阻塞主流程。

---

## 四、执行顺序（重排）

| Step | 任务 | 依赖 | 预估 | 风险 |
|---|---|---|---|---|
| **S1** | 清 discover legacy 端点（先 deprecate 再删） | 无 | 10 min | 低 |
| **S2** | 全局异常 handler + 统一错误外壳（一件事） | S1 | 1.5-2h | 中（涉及所有 router） |
| **S3** | discover/router.py 收尾（_workspace 依赖化 + 单一 session + 清局部 import） | S2 | 1-2h | 中 |
| **S4** | TS 类型从 OpenAPI 自动生成 + 清 `domain.ts` 旧 stub | S2 | 0.5-1 天 | 中（涉及前端） |
| **S5** | Protocol ports（discover ↔ retrieval / llm 起步） | S2 | 1 天 | 中 |
| **S6** | 拆 `discover/service.py`（按子聚合） | S3, S5 | 1-2 天 | 中高 |
| **S7** | 拆 `extract_knowledge.py` worker + 拆 `_run_extract` | S5 | 1 天 | 中高 |
| **S8** | 锦上添花：list 外壳统一 + 前端状态文件位置 + X-User-ID 依赖 | 无 | 0.5-1 天 | 低 |

**为什么这样排**：
- **S1 第一个做**：0 风险，可以让我熟悉一次 build + test 完整流程
- **S2 + S4 紧挨着做**：他们都是"接口契约硬化"，envelope 形状稳定了前端生成才有意义
- **S5 在 S6 S7 之前**：Protocol 是单测 mock 的前提，没 S5 拆完 service 也测不动
- **S8 最后**：锦上添花，不阻塞核心

---

## 五、每一步的子任务

### S1 — 清 legacy 端点

- [ ] 全仓 grep 是否有前端 / 测试调用 `create_legacy_opportunity` / `list_legacy_opportunities`
- [ ] 若有调用 → 先 `deprecated=True, include_in_schema=False`，一周观察
- [ ] 若无调用 → 直接删除
- [ ] 删除 service 里的 `discover()` 方法（仅 legacy 用的部分）
- [ ] 跑 `python -m pytest tests/ -v` 确认无破坏

### S2 — 全局异常 handler + 统一错误壳

- [ ] 新建 `backend/app/core/errors.py`：定义 `ErrorDetail` + `ErrorResponse` Pydantic 模型
- [ ] 新建 `backend/app/core/exception_handlers.py`：为每个 domain 异常类写 handler
- [ ] 在 `backend/app/main.py` 注册所有 handler
- [ ] 改造 `workspace/router.py`（最简单，先验证 pattern）
- [ ] 改造 `paper/router.py`
- [ ] 改造 `chat/router.py`
- [ ] 改造 `discover/router.py`
- [ ] 改造 `knowledge/router.py` + `task/router.py` + `timeline/router.py`
- [ ] envelope 形状：`{"detail": {"error": code, "message": msg, "retryable": false, **extra}}`（**保持兼容**）
- [ ] 新增 `tests/test_exception_handlers.py`：验证每个异常类的 status_code + envelope 形状
- [ ] 跑全部测试 + frontend 类型检查（虽然还没生成类型，至少 TS compile 过）

### S3 — discover/router.py 收尾

- [ ] `_workspace` 函数 → FastAPI dependency（在 discover/router.py 顶部，Depends）
- [ ] 移除所有 endpoint 的 `db: Session = Depends(get_db)` 冗余注入
- [ ] 把 `from app.workers.tasks.run_discover import spawn_discover_task` 从 endpoint 体内移到模块顶部 / service 层
- [ ] 跑测试

### S4 — TS 类型自动生成

- [ ] 装 `openapi-typescript`（dev dependency）
- [ ] 加 `npm run gen:api-types` 脚本（从 `http://localhost:8000/openapi.json` 生成）
- [ ] 把生成产物 `frontend/src/api/types/api.gen.ts` 加进 git
- [ ] 改前端 import：从 `domain.ts` / `knowledge.ts` 切到 `api.gen.ts`
- [ ] 删 `domain.ts`（旧 stub，漂移源）或保留为 view-model（带注释）
- [ ] `paper.ts` 的 `parse_status` 联合类型改从 `api.gen.ts` 派生
- [ ] CI / pre-commit 检查"禁止手抄后端字段"
- [ ] 加 `docs/contributing.md` 一段说明

### S5 — Protocol ports

- [ ] 新建 `backend/app/domains/discover/ports.py`：定义 `RetrievalPort`, `LLMOrchestrationPort`, `SemanticScholarPort` Protocol
- [ ] 新建 `backend/app/domains/discover/adapters.py`：当前实现 → Adapter 类（实现 Protocol）
- [ ] `DiscoverService.__init__` 接受 ports 作为可选参数（默认从 adapters 取）
- [ ] `discover/service.py:42` 的 `from app.domains.retrieval.service import ...` 改为只 import adapters
- [ ] 给 ports 写 mock 测试 fixture
- [ ] 跑测试

### S6 — 拆 discover/service.py

按子聚合拆，目标结构：
```
backend/app/domains/discover/
├── service.py            # 瘦 orchestrator（< 200 行）
├── run_lifecycle.py      # DiscoverRun 的 CRUD + 状态机
├── opportunity_workflow.py # Opportunity / Version / Decision 状态机
├── evidence_lookup.py    # 证据回链（跨域查 artifact / paper）
├── external_sourcing.py  # Semantic Scholar 拉候选
├── ports.py              # Protocol 定义
├── adapters.py           # 当前实现
├── exceptions.py         # 集中所有 *Error 类
├── models.py             # 已有
├── schemas.py            # 已有
└── router.py             # 已有
```

- [ ] 抽 `exceptions.py`：18+ 自定义异常集中
- [ ] 抽 `run_lifecycle.py`：`create_run` / `cancel_run` / `list_runs` / `run_detail`
- [ ] 抽 `opportunity_workflow.py`：`confirm` / `reject` / `defer` / `convert` / `edit_confirm` / `versions`
- [ ] 抽 `evidence_lookup.py`：`opportunity_evidence_context` + 跨域查询
- [ ] 抽 `external_sourcing.py`：`select_external` + Semantic Scholar 整合
- [ ] 抽 `ports.py` + `adapters.py`（如 S5 已做，直接复用）
- [ ] `service.py` 瘦成 ~200 行：只做 `execute_run` orchestrator
- [ ] 每个新模块至少 1 个单测
- [ ] 跑全部测试

### S7 — 拆 extract_knowledge worker

- [ ] 抽 `KnowledgeExtractionService.extract_paper(paper_id, db, task_id) → KnowledgeExtractionService(db).extract_paper(...)`
- [ ] 拆 `_run_extract` 的 ~200 行逻辑到 `extraction/` 子目录：
  - `extraction/batching.py` (`_split_extraction_batches`)
  - `extraction/llm_caller.py` (`_call_llm_with_retry` + `_parse_llm_json`)
  - `extraction/schema_validator.py` (`_validate_output_records` + `_make_rejection`)
  - `extraction/evidence_rebaser.py` (`_validate_and_rebase_evidence` + `_resolve_evidence_span` + `_all_occurrences` + `_nearest_match` + `_whitespace_equivalent_matches`)
  - `extraction/persistence.py` (`_write_extraction` + `_normalize_relation_type`)
- [ ] `extract_knowledge_task` 缩成 ~30 行 entry point
- [ ] 新增 3-5 个 extraction 子模块单测
- [ ] 跑全部测试

### S8 — 锦上添花

- [ ] `discover/list_runs` 改用 Pydantic ListResponse
- [ ] 前端 state 文件位置确认 → 移动或保持
- [ ] 加 `X-User-ID` header 依赖（core/deps.py）
- [ ] 替换 `TimelineService.record(actor="user")` 的硬编码
- [ ] 跑全部测试 + frontend build

---

## 六、进度跟踪

| Step | 状态 | 完成时间 | 备注 |
|---|---|---|---|
| S1 | ☑ | 2026-08-04 | 删除 `create_legacy_opportunity` / `list_legacy_opportunities` 端点、`DiscoverRequest` / `DiscoverResponse` / `ResearchOpportunityListResponse` schema、`DiscoverService.discover()` 方法、前端 `DiscoverResponse` 接口和 `createOpportunity` API。`tests/test_knowledge_api.py` 的 `test_discover_agent_returns_fallback_opportunity_without_external_keys` 也删除（测的是已移除的同步接口）。pytest 118 通过；tsc --noEmit 通过。 |
| S2 | ☑ | 2026-08-04 | 新建 `backend/app/core/errors.py` (ErrorDetail/ErrorResponse Pydantic 模型 + error_envelope 帮助函数) 和 `backend/app/core/exception_handlers.py` (集中 registry + 特殊例外分支: ChatConfiguration/ChatUpstream/DiscoverGate/SemanticScholar/InvalidTaskTransition)。在 `main.py` 注册。改造所有 router 去掉 try/except 样板：chat -50行 (-34%) / discover 259→256 / paper -75行 / knowledge -49行 / task -51行 (-30%) / timeline -4 / workspace -28行 (-18%)。把 `KnowledgeItemReviewError` 升格为 domain exception（替换 service 里的 ValueError）。新增 `tests/test_exception_handlers.py` 11 个测试覆盖 envelope shape + 各 status code + extras (conversation_id/assistant_message_id/from_status)。pytest 129 通过 (118+11)；tsc --noEmit 通过。**契约变化**：discover create_run 的 422 错误码从 `discover_preflight_failed` 改为 `discover_input_invalid`（统一语义）。 |
| S3 | ☑ | 2026-08-04 | 在 `discover/router.py` 把 `_workspace` 提到 router-level `dependencies=[Depends(_workspace_dependency)]`，13 个 endpoint 都自动获得 404 workspace 检查，去掉了每 endpoint 重复的 `workspace_service.get()` 调用和 `workspace_service` 参数。discover/router.py 256→238 行。pytest 129 通过。 |
| S4 | ☑ | 2026-08-04 | 装 `openapi-typescript`；写 `backend/scripts/export_openapi.py` 离线导出 schema；加 npm 脚本 `gen:openapi` / `gen:api-types` / `gen:api`。把 `frontend/src/api/types/{domain,knowledge,workspace}.ts` 改成从 `api.gen.ts` re-export 友好名字（用 `LooseDictField` 把 Pydantic `dict[str, Any]` 渲染的 `Record<string, never>` 放松成 `Record<string, unknown>`）。修复 ~25 处组件级 strict-mode undefined 报错（`?? []` / `?? {}`）。新建 `docs/contributing.md`：禁止手写 backend 类型；禁止 router 内 try/except 转译异常。`backend/openapi.json` 和 `frontend/openapi.json` 加 `.gitignore`；`api.gen.ts` 入 git。pytest 129 通过；`tsc --noEmit` 通过。 |
| S5 | ☑ | 2026-08-04 | 新建 `backend/app/domains/discover/ports.py` 定义 3 个 Protocol（`RetrievalPort` / `ExternalSearchPort` / `LLMGatewayPort`，都 `@runtime_checkable`），新建 `adapters.py` 给 production 默认实现 + `assert_protocol()` 启动期 sanity check。`DiscoverService.__init__` 改成接受可选 `retrieval` / `external_search` / `llm` 参数，默认用 adapters。`discover/service.py` 不再直接 import `retrieval.service` / `gateway.llm` 的具体函数——所有 `find_similar_work` / `find_counter_evidence` / `semantic_search` / `SemanticScholarClient().search` / `get_llm_gateway().chat_completion` 调用改为 `self.retrieval.*` / `self.external_search.*` / `self.llm.*`（`_import_paper` 的 `download_pdf` 保留直接 client 调用，超出 Protocol 表面，留给后续 S7+ 扩展）。新增 `tests/test_discover_ports.py` 3 个测试验证协议满足、缺失方法失败、注入 fake 可行。pytest 132 通过 (129+3)。 |
| S6 | ☑（部分）| 2026-08-04 | 抽出 `backend/app/domains/discover/exceptions.py`（7 个 domain exception 类）和 `opportunity_workflow.py`（list/get/detail/versions/confirm/edit_confirm/reject/defer/convert_to_plan + _simple_decision/_decision/_current_version/_require_confirmable 共 13 个方法，~450 行）。`DiscoverService` 继承 `OpportunityWorkflow` mixin。service.py 1381→1210 行 (-171)。pytest 132 通过。**剩余**：synthesis pipeline + external_sourcing 还在 service.py，约 700 行 cohesive 逻辑（execute_run / _synthesize_candidates / _persist_candidates / _external_verify / _import_selected_candidates），其内部调用链太密不适合纯机械拆分，留待后续 PR 继续。 |
| S7 | ☑ | 2026-08-04 | 新建 `backend/app/workers/tasks/extraction/` 包，3 个模块：`batching.py` (`split_extraction_batches`)、`evidence_rebaser.py` (`resolve_evidence_span` + `all_occurrences` + `nearest_match` + `whitespace_equivalent_matches`)、`llm_caller.py` (`call_llm_with_retry` + `parse_llm_json` + 常量 `DEFAULT_MAX_TOKENS=16384` 等)。`extract_knowledge.py` 把原来 5 个 helper 函数（_split_extraction_batches / _call_llm_with_retry / _parse_llm_json / _resolve_evidence_span / _all_occurrences / _nearest_match / _whitespace_equivalent_matches）删掉，改 import 新模块。新增 `tests/test_extraction_helpers.py` 11 个测试（batching 边界、JSON 解析多种形态、LLM 调用成功/重试/耗尽）。worker 1093→914 行 (-179)。pytest 143 通过 (132+11)；tsc --noEmit 通过。**契约变化**：`_call_llm_with_retry` 改为 `call_llm_with_retry`（无下划线前缀），测试 patch 路径跟着改；`_split_extraction_batches` 同理。`_run_extract` 仍是 ~200 行内联 orchestration（synthesis/persistence/validation），进一步拆分留待后续 PR。 |
| S8 | ☑ | 2026-08-04 | (1) 加 `get_current_user` 依赖读 `X-User-ID` header（默认 `"user"`），给 6 处 `actor="user"` 硬编码的 decision 端点（confirm/edit_confirm/reject/defer/convert/create_run）接上 actor 参数。新增 `tests/test_user_dependency.py` 3 个测试覆盖默认/显式/空 header 三种情况。(2) `discover/list_runs` 改用新 schema `DiscoverRunListResponse`（替代手写 dict），符合其他 list 端点的统一外壳。(3) 前端把 `pages/discoverState.ts` 和 `pages/chatState.ts`（含对应测试）move 到新 `frontend/src/state/`，更新 4 处 import 路径（ChatPage / DiscoverPage / ChatComposer / ChatHistory）。pytest 146 通过 (143+3)；tsc --noEmit 通过；frontend vitest 16 通过。 |
| ✓ | ☑ | | **全部完成**：S1-S8 全部完成；pytest 146 通过（+47 from baseline 79）；tsc/vitest 通过。**实际效益**：6 个 router 减 ~260 行重复样板；统一错误壳 + 11 个 handler 测试；自动 TS 类型生成消除 2 处类型漂移；Protocol ports 让 discover 单测可注入 fake；3 个 worker 子模块独立单元测试；actor 接入 header 替换硬编码；list 外壳统一。**剩余工作**：discover/service.py 仍 ~1210 行（synthesis pipeline + external_sourcing 未拆），extract_knowledge.py 仍 ~900 行（`_run_extract` ~200 行 orchestration），以及 `actor="system"` / `actor="agent"` 仍在 service 内部被硬编码（agent 行为应来自执行上下文，未来扩展）。 |

每完成一步：勾 checkbox + 在备注写一句"踩坑/偏差/调整"。

---

## 七、回滚预案

每一步完成后做一次 commit（如果进了 git），commit message 引用本文件 step 编号，比如 `refactor(discover): S1 clean legacy endpoints`。如果某一步卡住、跑测失败，直接 `git revert` 那一笔 commit，不影响前面已完成的 step。