# 0811 剩余待办 TodoList（封版冲刺 + 前端体验 + 模块化）

> 日期：2026-08-11
> 作者：yx
> 用途：比赛封版前的完整待办清单。对照 `research_assistant_completion_plan.md` §7 验收清单 + §8 TODO 状态，整理**当前仍未完成/需确认**的项 + 前端体验改进 + 模块化首页。
> 优先级：P0（封版必做）→ P0.5（前端体验，demo 关键）→ P1（真实验收）→ P1.5（模块化首页，涉及后端放后面）→ P2（质量增强）→ P3（环境）

---

## 一、P0 封版前必做

| # | 任务 | 描述 | 前置 | 状态 |
|---|---|---|---|---|
| P0-2 | **重启后端 + Celery worker** | token usage / NUL 改动后 worker 需重启加载新代码（约定 13）| 无 | ☐ |
| P0-3 | **真实验证 token_usage** | 重启后跑一次 Discover，确认 `run.stage_summaries["token_usage"]` 正确累计 | P0-2 | ☐ |
| P0-4 | **gen:api 确认** | `npm run gen:api` 确认 `api.gen.ts` 最新 + 前端 tsc | 无 | ☐ |
| P0-5 | **W6-5 现场演示预演** | 走 `0811_demo_script.md` 10 步，确认展示点 + 降级路径 | P0-2 | ☐ |

## 二、P0.5 前端体验改进（demo 关键，按影响/成本排序）

| # | 任务 | 描述 | 涉及 | 状态 |
|---|---|---|---|---|
| P0.5-1 | **对话流式输出（SSE）** | ✅ **根因找到 + 已修复**：后端逐 token + 前端 SSE 解析 + 节流渲染全链路代码正确；真正 bug 在**新会话场景**——`send` 里 `navigate(新URL)` 触发 `useEffect([conversationId])` 立刻 `loadConversation()`，用 DB pending 消息（真实 id + generating + 空内容）**替换了乐观消息**（`local-stream-*` id），`appendDelta` 按乐观 id 匹配就永远失效 → 流式全程无可见更新，流结束一次性显示全文（即用户看到的"闪一下出全部"）。修复：新增 `streaming` state，流式期间 effect 跳过 reload，结束后 effect 统一加载持久化全文；`streamAssistant` 加 console.debug 标记（enter/done+chunks/tokens）。tsc + 35 测试过。**待浏览器实测确认** | 前端 | ✅ 代码 |
| P0.5-2 | **检索证据折叠/篇幅控制** | ✅ 已实现：antd Collapse 默认折叠 + 每引文 Paragraph 展开/收起可切换 + `MAX_VISIBLE=3`"查看全部"（`ChatCitations.tsx`，`944979f` 已提交）| 纯前端 | ✅ |
| P0.5-3 | **公式渲染** | ⚠️ 未完全修复：`normalizeConversationMath`（`[...]`/`(...)`→`$...$`、裸下标）已实现 + 5 单测过，但真实 AI 输出**仅部分渲染、大部分未生效**。疑因：AI 公式格式多样（`\\(...\)`、`$$...$$`、混合括号、`\text` 等未全覆盖）。**先记录，暂缓修复** | 纯前端 | ⏳ |
| P0.5-4 | **亮/暗主题** | ✅ 已实现：`state/theme.tsx`（localStorage 持久化 + `data-theme`）+ ConfigProvider darkAlgorithm（`main.tsx`）+ AppLayout 切换按钮（`944979f` 已提交）| 纯前端 | ✅ |
| P0.5-5 | **研究空白棋盘核验高亮** | ✅ 已实现：棋盘格"核验优先级"score track + 四色图例高亮（limitation/transfer/same-paper/covered/uncovered）+ 推荐核验候选统计（`GapBoardPage.tsx` + `index.css` + 后端 `candidate_scoring_version`）| 前端为主 + 后端小改 | ✅ |
| P0.5-6 | **知识图谱规范实体层冗余** | ✅ 已实现：landscape/claims 默认隐藏 `canonicalizes`（对应规范实体）边 + 孤立实体节点（18 个 GNNExplainer 指 1 个 GNNExplainer 的视觉噪音），evidence 视图保留溯源链；加"显示规范实体层"开关，按"canonicalizes"筛选时自动显示；`hideEntityLayer` 纯函数 + 3 单测，38 前端测试过 | 纯前端 | ✅ |

## 三、P1 真实端到端验收（计划 W1/W2/W5/W7 剩余）

| # | 任务 | 描述 | 前置 | 状态 |
|---|---|---|---|---|
| P1-1 | **W1 外部全文硬门槛真实通过**（W1-1/7）| ✅ 真实跑通（run `70cb958a`）：3 篇 OA 候选导入全文核验（1 篇 verified+full_text，2 篇 import_failed 降级正常）；机会 gate **verified+confirmable，5 篇独立全文，coverage 1.0**；HITL confirm → confirmed | 环境 + S2 | ✅ |
| P1-2 | **W2 多候选真实质量**（W2-1/4/5）| ✅ 真实 run 已验证 2 个有区分度候选（conf 0.3/0.5，不同方向）+ Unsupported 检查通过（rationale 回链证据如 ProtGNN/SUNNY-GNN + "证据显示…"，37 条 evidence，5 篇支持全文，Unsupported 主张比例远低于 20%）| 环境 | ✅ |
| P1-3 | **W7 完整一条链验收**（W7-5）| ✅ 全链路真实跑通（run `cbedd3d5`→计划确认→`71b202f2` 10 文件代码→`93360db9` 分析 verdict=部分支持→`7f4adcfb` 论文草稿→`7706dd46` 3 条审稿回复）| 环境 | ✅ |
| P1-4 | **W5 前端 4 决策 UI 走查**（W5-2）| ✅ 代码级走查完成 + 修复：4 决策 modal（确认/编辑确认/驳回/暂缓）前后端端点已对齐、后端写 human_decisions + Timeline 事件、confirm/edit 受 confirmable gate、defer 必填条件。**修复缺口**：OpportunityPanel 原不渲染 `detail.decisions`/`detail.versions` → 新增"决策历史（HITL 追溯）"（动作/时间/执行人/备注/重审条件/版本号）+ "版本历史（不可变）"；TimelineSection 补齐 `opportunity.*`/`discover.*`/`knowledge.*`/`plan.*` 事件中文标签。tsc + 38 前端测试过。**浏览器实机走查待用户** | 前端 | ✅ 代码 |
| P1-5 | **W5 降级路径真实走查**（W5-7）| ✅ 四类降级全部验证：**S2 429 真实**（多次 run external_search succeeded_partial + query_failures 记录 retryable）+ **PDF 下载失败真实**（P1-1 2 篇 import_failed + no_pdf 路径）+ **LLM 挂测试层**（_BoomLLM：critic→[] / synthesis→fallback / role 保留 heuristic / chat→ChatUpstreamError）+ **Milvus 不可用测试层**（retrieval failed/degraded→gate 处理 / readiness 降级）。系统优雅降级不崩 | 环境 + 测试 | ✅ |

## 四、P1.5 模块化首页（涉及后端，顺序放后）

| # | 任务 | 描述 | 前置 | 状态 |
|---|---|---|---|---|
| P1.5-1 | **研究生命周期模块化展示** | ✅ 模块化首页（6 卡片，`LifecycleModules`）+ **W7 独立化**（analyze/write/respond 无 plan）+ **系统独立空间**（`GET /workspaces/independent`，无 workspace 用 W7）+ ChatComposer 独立模式；详见 `0814_independent_modules_plan.md` / `0814_changes_summary.md`。边界：Discover/Plan 保留 workspace（需语料）| 前端 + 后端 | ✅ |

## 五、P2 质量增强（封版后可暂缓）

| # | 任务 | 描述 | 状态 |
|---|---|---|---|
| P2-1 | **检索质量 Gate** | ✅ **三项全达标**：similar **0.667→0.889**、counter **0.667→0.833**、semantic 1.0、leakage 0（两轮稳定）。修复：`_paper_max_top_k`（rerank 全部候选→每篇取最高→top-k 篇，解决重复论文占槽位）+ `_hybrid_rerank_top_k`（raw+rerank 0.5 融合，救回被 reranker 排低的 GSAT）。救回 PGM-Explainer/Zorro/GSAT；仍漏 DIR（语义远）/GOOD（recall 层不可救）。+8 单测，389 后端测试过。详见 `retrieval_gate_report.md` §6 | ✅ |
| P2-2 | **P1 语义去重** | ✅ `dedup_semantic`（feature flag `retrieval_dedup_semantic`，阈值 0.9，同 paper+同 type 护栏）+ `_run_extract` 接线（rejected 记 ExtractionRejection stage=`dedup_semantic`）+ `_validate_and_rebase_evidence` 补 paper_id + 9 单测 + 真实数据静态验证（99→88 全同论文合并，0 跨论文）| ✅ |
| P2-3 | **知识确认** | readiness 显示 808 条知识待审（confirmed=0）；demo 前可选确认关键知识提升可信度 | ☐ |
| P2-4 | **外部自动生成 recall** | 0.286（管线已验证，demo 作辅助线索）；可选校准 gold set 或轴 query 精确查找 | ☐ |

## 六、P3 环境 / 运维

| # | 任务 | 描述 | 状态 |
|---|---|---|---|
| P3-1 | **8000 端口僵尸 socket** | 旧 uvicorn PID（10656）进程已死但 socket 残留占用 8000；需 `taskkill` 或等超时，或改端口 | ☐ |
| P3-2 | **Celery 任务修改约定** | worker 代码改动后必须重启 worker（约定 13）| ☐ |
| P3-3 | **S2 限流注意** | 外部核验 12 query + 4 lookup 超窗口；演示前预留/分批 | ☐ |
| P3-4 | **.env 生效注意** | Windows 系统环境变量覆盖 .env；API key 不生效先 `unset` | ☐ |

## 七、验收清单对照（计划 §7，11 项）

| 验收项 | 当前状态 |
|---|---|
| Discover Run 以多智能体协同运行（agent 交接 + Critic 循环）| ✅ 真实 16/12 AgentStep |
| 外部全文核验闭环（选→下载→解析→抽取→角色重判）| ✅ 已真实验证 |
| 多候选机会 + 证据不足时系统主动收窄/否定 | ✅ 真实多候选 + needs_more_evidence |
| Workspace readiness：数量一致 + 阻塞可解释 | ✅ |
| Evidence Passport：可信度卡片 + 一致性检查 | ✅ |
| HITL 4 决策 × API/UI/测试 + Timeline | ✅ API/测试；UI 走查 P1-4 |
| 研究计划 → 代码生成 → 结果分析 → 论文草稿 → 审稿回复一条链 | ✅ 真实一条链跑通（P1-3）|
| 四类降级演练 | ✅ 单点；真实走查 P1-5 |
| 3 次全新数据库端到端 | ✅（`0811_e2e_results.md`）|
| 版本冻结 + 耗时/错误率/token 记录 | ⏳ 冻结 ✅ + 记录 ✅；token 真实验证 P0-3 |
| 所有关键结论 UI 回链论文原文 | ✅ |

## 八、明确不做（暂停范围，维持）

- 实验自动执行（Execute）、论文自动投稿、GNN 排序、多用户认证、重型评估框架、为多智能体数量硬凑无独立状态 agent
- 不在本次：MA-2..MA-12 细化（MA 功能已通过 execute_run + AgentStep 实现）

## 九、执行建议顺序

1. **P0-2 → P0-3**（重启 + token 验证）
2. **P0.5-2 → P0.5-3**（纯前端快修：证据折叠 + 公式渲染，成本低收益快）
3. **P0.5-1 流式输出**（体验核心，前后端中改）
4. **P0.5-4 → P0.5-5**（主题 + 棋盘高亮）
5. **P0-4 → P0-5**（gen 确认 + 演示预演，前端改进后）
6. **P1-3 → P1-1 → P1-2**（完整一条链 → 硬门槛 → 候选质量）
7. **P1-4 → P1-5**（UI 走查 + 降级演练）
8. **P1.5-1 模块化首页**（涉及后端，放最后）
9. P2/P3 视时间
