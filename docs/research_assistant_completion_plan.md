# GapMind 后续功能完善计划（多智能体协同 + 全生命周期）

> 更新日期：2026-08-08
> 状态：规划稿（v2，合入 PR #15 后重排）
> 关联：`functional_roadmap.md`（功能层现状）+ `external_novelty_gate_report.md`（Stage 3 Gate）+ `zwx_recent_work_handoff_20260808.md`（PR #15 交接）+ `0808_to_improve.md`（zwx 总体优化建议）

---

## 1. 战略目标

比赛提交题目：**基于学科领域大模型与多智能体协同的科研辅助系统**。

**2026-08-08 现状**：zwx 的 PR #15 已合入（`3fac02c`）。系统已具备：
- **Agent 运行框架**（`agent/` 域）：`AgentRun / AgentStep / AgentArtifact` 统一运行协议 + `research_plan`（人工确认 Gate）与 `code_generation` 两类受控 agent + 可选 Docker 沙箱验证；
- **Workspace RAG 对话**：grounded 回答 + 持久化 Evidence 引用 + 原文定位；
- **研究中心**：Opportunity Portfolio + Research Plans 列表；
- **Discover 修复**：软删除 / 跳过外部选择 / 阶段状态；
- **知识工作台 + 知识图谱**：单/双列、可定位搜索、懒加载；
- 284 后端测试 + 20 前端测试。

但仍缺两件对齐题目的关键事：
1. **多智能体协同**：现有 `research_plan`/`code_generation` 是两个**独立的受控工作流**，不是多个角色围绕同一研究问题协作。`DiscoverService.execute_run` 仍是单管线（~1800 行单体编排），LLM 角色分工未以 agent 形态呈现。
2. **研究全生命周期**：闭环停在"计划 + 代码产物"，结果分析 / 论文写作 / 审稿回复未闭合。

本计划核心目标：
1. **复用 zwx 的 AgentRun/Step/Artifact 协议**，把 Discover 单管线升级为有界多智能体协同（Planner/Evidence/ExternalNovelty/Critic/Opportunity/Gate），对齐题目且 demo 可展示 agent 交接；
2. **补全研究生命周期**（结果分析 → 论文写作 → 审稿回复）；
3. **统一研究准备度 + 证据可信度**（zwx P0-1/P0-2），让 demo 的"可信度叙事"有说服力；
4. 保持 GapMind 核心原则：**一切 LLM 产物回链证据，不成为未验证事实；关键资产由用户确认**。

---

## 2. 端到端系统形态（验收基准）

```
1. 导入论文 → 解析 → 知识抽取，每条回链原文                        [已能]
2. Workspace 检索：语义搜 / 相似 / 反证（来源排除 + 角色排序）       [已能，质量中等]
3. Workspace RAG 对话（grounded + 证据引用 + 原文定位）             [已能（PR #15）]
4. Discover Run（多智能体协同）：
   Planner 分解 → Evidence 检索 → ExternalNovelty 外部核验
   → Opportunity 综合 → Critic 挑战 → Gate 校验 →（收窄/否定）→ 多候选 [MA 后]
5. 外部全文核验：选 OA PDF → 下载 → 解析 → 抽取 → 全文回链 → 角色重判   [W1]
6. HITL 决策：确认/编辑确认/拒绝/延后 + Timeline + 版本 diff          [已能]
7. 研究中心：Portfolio + Research Plans + Agent 运行                [已能（PR #15）]
8. 研究计划：Research Plan Agent 生成草稿 → 人工确认                 [已能（PR #15）]
9. 代码生成：Code Generation Agent → 预览/下载/可选沙箱验证           [已能（PR #15）]
10. 结果分析：上传实验结果 → 对照证伪标准 → 结论                      [W7]
11. 论文写作 / 审稿回复：机会+计划+证据 → 草稿                        [W7]
12. 研究准备度：统一"能做什么/为什么不能/下一步去哪"                   [W0]
13. 证据可信度：Evidence Passport 卡片（覆盖/全文/反证/核验/人工）     [W3]
14. 降级路径：S2 429 / LLM 挂 / agent 失败 → 系统降级仍可用           [W5]
15. 封版演示：3 次全新 DB 端到端，冻结版本，记录耗时/错误率/token      [W6]
```

---

## 3. 多智能体架构设计（核心）

### 3.1 复用 zwx 的 Agent 运行协议

**不再新建第二套状态系统。** `agent/` 域的 `AgentRun / AgentStep / AgentArtifact` 已是统一协议：

- `AgentRun`：workspace 隔离、conversation 关联、`context_snapshot`（可审计输入快照）、status/progress/current_stage、`requires_confirmation`
- `AgentStep`：序列化阶段记录（stage/status/summary/details）——即 **agent 交接的可视化数据源**
- `AgentArtifact`：typed 产物（research_plan.md / code 文件），可预览、下载、ZIP

当前 `research_plan` / `code_generation` 是两个受控工作流。**MA 在此之上扩展角色 agent**，而不是另起炉灶。

### 3.2 角色 agent（在 agent 域扩展）

| Agent | 职责 | 复用现有 |
|---|---|---|
| **PlannerAgent** | 分解研究问题 → 生成检索计划 → 交给 Evidence/ExternalNovelty | 新 LLM 角色 |
| **EvidenceAgent** | workspace 检索（语义/相似/反证）+ 证据装配 | `_workspace_similar/_counter/_supporting` |
| **ExternalNoveltyAgent** | 外部 query 构造 + S2 检索 + 角色判别 + 全文核验 | `_external_query_plan/_external_verify` |
| **CriticAgent**（新）| 对抗性审查：找反证缺口、挑战假设、检查"是否真没人做过"→ challenges + 收窄建议 | 新 LLM 角色 |
| **OpportunityAgent** | 从证据 + Critic 反馈综合机会候选 | `_synthesize_candidates` |
| **GateAgent** | 硬门槛（≥2 独立全文）+ needs_more_evidence 明细 | `_evidence_gate` |
| **PlanAgent** | 已确认机会 → 研究计划（已有 research_plan agent）| 现有 agent |
| **AnalyzeAgent / WriteAgent / RespondAgent** | W7 全生命周期 | 新（W7）|

**落地方式二选一**：
- (a) 在 `agent/` 域注册新 `agent_type`（`discover_planner` 等），Orchestrator 串起各 agent step；
- (b) 重构 `DiscoverService.execute_run`，把内部阶段映射为 `AgentRun + AgentStep` 记录，角色 prompt 拆分。

推荐 **(b)**：Discover 是本轮核心场景，先在 `execute_run` 内落地角色拆分 + AgentStep 持久化，稳定后再泛化到 agent 域注册。

### 3.3 Orchestrator 循环

```
Planner 分解
  → [Evidence, ExternalNovelty] 收集
  → Opportunity 综合（多候选）
  → Critic 挑战
       ├─ 无 gap → Gate 校验 → PlanAgent（人工确认）
       └─ 有 gap → Orchestrator 决定：
             ├─ 收窄：换角度重试（补证据 / 换检索词）→ 回到 Evidence/ExternalNovelty
             └─ 否定：标记弱机会 + 理由 → 返回用户（demo 亮点"系统主动收窄/否定"）
```

**Critic 循环天然吸收原 W3（自主收窄/重试）**。

### 3.4 拆分 DiscoverService

`DiscoverService`（~1800 行）按职责拆为可测试服务：运行生命周期 / 外部检索 / 证据装配 / 候选综合 / Gate / 持久化；Orchestrator 只负责状态推进。每个 Agent 独立单测 + 固定案例端到端。

### 3.5 ResearchContext + Timeline

共享对象：研究问题 + 证据账本（支持/相似/反证/外部全文，带回链）+ 机会候选（含 Critic 反馈）+ gate 状态 + **agent_log**（写 `discover.agent.*` timeline 事件）。前端用 `AgentStep` 展示 agent 交接流。

### 3.6 领域大模型接入（已对齐）

`gateway/llm.py` 模型无关（`DEEPSEEK_MODEL` 可配）；zf 的 Qwen3:8B+LoRA 就绪后即插即用。

---

## 4. 工作流分解

### MA — Discover 多智能体协同（架构底座，最高优先级）

- **现状**：`execute_run` 单管线；agent 域已有 AgentRun/Step/Artifact + research_plan/code_generation
- **工作**：
  1. 拆 `DiscoverService`（运行/检索/综合/Gate/持久化）
  2. `execute_run` 重构为 Orchestrator：Planner → Evidence → ExternalNovelty → Opportunity → Critic → Gate，阶段写 `AgentStep`
  3. CriticAgent（新角色）
  4. Orchestrator 决策逻辑：Critic 有 gap → 收窄/否定
  5. agent_log → Timeline（`discover.agent.*`）
- **验收**：主 Case 跑通 agent 协调；Critic 挑战 → 收窄/否定可见；`AgentStep` 记录交接；284 测试绿
- **依赖**：无

### W0 — 研究准备度与下一步（zwx P0-1）

- **现状**：用户要自己判断"能否 Discover/为何不能确认/下一步去哪"；概览页多请求各自算数
- **工作**：后端 `WorkspaceReadinessService` + `GET /workspaces/{id}/readiness`（corpus/retrieval/knowledge/discover/research 五维 ready + blocking_actions + recommended_next）；前端紧凑进度条
- **验收**：首页/概览/Discover/研究中心数量一致；任意阻塞可解释"为何 + 去哪"
- **依赖**：无；可与 MA 并行

### W1 — 外部全文核验闭环端到端

- **现状**：`import_selected_candidates` + `resume_discover_runs_for_paper` 已建，未端到端验证；`skip_external_selection` 已建（PR #15）
- **工作**：选 1-2 个真实 OA 外部候选走全链路；修 bug（含 `openAccessPdf` 非 https URL 的规范化）；验证 `evidence_level` metadata→fulltext + 硬门槛计数；角色重判
- **验收**：外部候选走完全链路，机会硬门槛（≥2 独立全文）能过
- **依赖**：MA（角色 agent 包装）

### W2 — 机会生成质量验证

- **现状**：`_synthesize_candidates` 多候选已建，未质量验证
- **工作**：主 Case 跑 1-3 次看区分度；Critic 反馈注入 OpportunityAgent；生成审计字段（prompt/model/corpus/检索快照记入 run）
- **验收**：2-3 个有区分度候选；Unsupported ≤20%（可暂缓）
- **依赖**：MA, W1

### W3 — Evidence Passport 统一证据可信度（zwx P0-2）

- **现状**：EvidenceSpan / ChatMessageEvidence / OpportunityEvidence / Agent 上下文分属各模块，用户难分"模型自信 vs 检索相关 vs 覆盖率 vs 全文核验 vs 人工确认"
- **工作**：`EvidenceManifest`（先 API schema + JSON 快照，不新增复杂表），Chat/Opportunity/Plan/AgentArtifact 复用；前端"可信度卡片"；一致性检查（`[E1]` 引用必须存在 / 无引用标 unsupported / 版本过期标 stale）
- **验收**：各产物用同一套证据语义；关键结论一键回原文高亮；不存在的引用/过期引用被拦截或警告
- **依赖**：无；可与 MA 并行

### W4 — 前端：agent 交接呈现 + 证据可信度卡片

- **现状**：DiscoverPage 完整；Research Center（Portfolio/Plans）已建（PR #15）；ChatAgentRunCard 已建
- **工作**：Discover run 详情展示 agent 交接流（基于 `AgentStep`）；机会详情加 Evidence Passport 卡片；W3 一致性检查的前端告警
- **验收**：agent 交接 UI 可见；可信度卡片可见
- **依赖**：MA, W3

### W7 — 全生命周期 agent（Analyze / Write / Respond）

- **现状**：未建；已有 Research Plan + Code Generation 两类 agent
- **工作**：AnalyzeAgent（结果 JSON → 对照证伪标准 → 结论+证据）；WriteAgent（计划+证据 → 章节草稿）；RespondAgent（审稿意见 → 回复草稿）；前端入口
- **验收**：确认计划 → 模拟实验 → 分析结论 → 论文草稿 → 审稿回复一条链
- **依赖**：W3（Evidence Passport 供引用）
- **原则**：结果分析吃手动数据；产物回链证据；轻量不作 Gate

### W5 — 端到端验收 + 失败降级

- **工作**：HITL 4 决策 × API/UI/测试 + Timeline；S2 429 / LLM 挂 / Milvus 不可用 / PDF 下载失败四类降级演练；agent 失败 → Orchestrator 降级继续；重复点击幂等
- **验收**：正常 + 降级路径都跑通
- **依赖**：MA, W0, W1, W2, W3, W4

### W6 — 封版 + 演示预演

- **工作**：冻结版本（语料/标注/Prompt/模型/解析器/Schema）；3 次全新 DB 端到端；记录耗时/错误率/token；演示脚本（agent 交接 + 证据回链 + 可信度卡片）
- **依赖**：W5

---

## 5. 依赖与优先级

```
MA ──→ W1 ──→ W2 ───────┐
W0 / W3（可并行，demo 可信度叙事）│
MA → W4 ────────────────┤
W3 → W7 ────────────────┼→ W5 → W6
```

**优先级**：MA（对齐题目，架构底座）→ W0/W3（可信度叙事，并行）→ W1（外部全文）→ W2（机会质量）→ W4（前端，并行）→ W7（生命周期）→ W5（端到端）→ W6（封版）

---

## 6. 完整度评估

**对比赛 Demo 的 MVP 闭环：足够完整（MA + W0-W7 完成后）**

| 研究生命周期 | 状态 |
|---|---|
| 导入 → 抽取 → 证据回链 | ✅ 已完整 |
| Workspace 检索三合一 | ✅ 可用（质量中等）|
| Workspace RAG 对话（grounded）| ✅ PR #15 |
| 外部新颖性核验（metadata + 全文）| ✅ W1 后 |
| 多智能体协同（Planner/Critic 循环）| ✅ MA 后 |
| 多候选机会 + 证据门 + 收窄/否定 | ✅ MA/W2 后 |
| HITL 4 决策 + Timeline | ✅ 已能 |
| 研究计划（人工确认 Gate）| ✅ PR #15 |
| 代码生成（预览/下载/沙箱）| ✅ PR #15 |
| 结果分析 / 论文写作 / 审稿回复 | ✅ W7 后（轻量）|
| 研究准备度 + 证据可信度卡片 | ✅ W0/W3 后 |
| 降级路径 | ✅ W5 后 |
| 封版演示 | ✅ W6 后 |

**诚实缺口（不假装完整）**：
- 检索质量 Gate 未过（similar 0.778 / counter 0.667）——性能优化已搁置，demo 作 baseline
- 外部自动生成 recall 0.286——管线已验证、候选主题相关，demo 中作"辅助线索 + 人工选择"
- P1 语义去重 / 抽取模型微调（zf 并行）——质量增强，非 demo 阻塞

**明确不做（暂停范围）**：实验自动执行（Execute）、论文自动投稿、GNN 排序、多用户认证/协作、重型评估框架、为多智能体数量硬凑无独立状态的 agent。

---

## 7. 验收清单（end-to-end）

- [ ] Discover Run 以多智能体协同运行（agent 交接 + Critic 循环）
- [ ] 外部全文核验闭环（选→下载→解析→抽取→角色重判）
- [ ] 多候选机会 + 证据不足时系统主动收窄/否定
- [ ] Workspace readiness：数量一致 + 阻塞可解释
- [ ] Evidence Passport：可信度卡片 + 一致性检查
- [ ] HITL 4 决策 × API/UI/测试 + Timeline 追溯
- [ ] 研究计划 → 代码生成 → 结果分析 → 论文草稿 → 审稿回复一条链
- [ ] 四类降级演练（S2 429 / LLM / Milvus / PDF 下载）
- [ ] 3 次全新数据库端到端
- [ ] 版本冻结 + 耗时/错误率/token 记录
- [ ] 所有关键结论 UI 回链论文原文

---

## 8. 详细 TODO list

> 每个工作流拆成可执行项。编号即建议执行顺序。状态图例：☐ 未开始 / ⏳ 进行中 / ✅ 完成

### MA — Discover 多智能体协同（优先）

| # | TODO | 状态 |
|---|---|---|
| MA-1 | 拆分 `DiscoverService`（~1800 行）：运行生命周期 / 外部检索 / 证据装配 / 综合 / Gate / 持久化 | ☐ |
| MA-2 | 复用 `AgentRun/AgentStep` 协议：定义 Discover 编排的 step 序列（planner→evidence→external→opportunity→critic→gate）| ☐ |
| MA-3 | `execute_run` 重构为 Orchestrator：Planner 分解 → 调度 → 收集 → decide | ☐ |
| MA-4 | EvidenceAgent：包装 `_workspace_similar/_counter/_supporting` | ☐ |
| MA-5 | ExternalNoveltyAgent：包装 `_external_query_plan/_external_verify` + 角色判别 | ☐ |
| MA-6 | OpportunityAgent：包装 `_synthesize_candidates` | ☐ |
| MA-7 | GateAgent：包装 `_evidence_gate` + `needs_more_evidence` 明细 | ☐ |
| MA-8 | **CriticAgent（新）**：对抗性审查 → challenges + 收窄建议 | ☐ |
| MA-9 | Orchestrator 决策逻辑：Critic 有 gap → 收窄（换角度重试）/ 否定（标记弱机会+理由）| ☐ |
| MA-10 | agent step → Timeline（`discover.agent.*` 事件，含输入/输出摘要）| ☐ |
| MA-11 | 每 Agent 独立单测 + 固定案例端到端测试 | ☐ |
| MA-12 | 主 Case 端到端跑通（agent 交接可见 + Critic 收窄/否定可见）| ☐ |

### W0 — 研究准备度与下一步

| # | TODO | 状态 |
|---|---|---|
| W0-1 | `WorkspaceReadinessService`：五维 ready（corpus/retrieval/knowledge/discover/research）| ✅ |
| W0-2 | `GET /workspaces/{id}/readiness`：blocking_actions + recommended_next_action | ✅ |
| W0-3 | 前端紧凑进度条（文献→知识→发现→确认→计划→执行）+ 单一来源状态 | ✅ |
| W0-4 | 验收：各页面数量一致；阻塞可解释"为何 + 去哪" | ✅ |

### W1 — 外部全文核验闭环

| # | TODO | 状态 |
|---|---|---|
| W1-1 | 从 gold set 选 1-2 个可下载的 OA 外部候选 | ⏳ 待真实环境（需 S2 API）|
| W1-2 | 走通 `import_selected_candidates` 全链路（选→下载→parse→extract）| ⏳ 代码已就绪 + 单测，待 Celery 环境端到端 |
| W1-3 | 修下载/解析/抽取失败路径 bug（含 openAccessPdf 非 https URL 规范化）| ✅ `_normalize_pdf_url`（http:// 与 // 前缀 → https；arxiv abs→pdf）+ import_failed/no_pdf 路径测试 |
| W1-4 | 验证 `evidence_level` metadata→fulltext + 硬门槛（≥2 独立全文）计数 | ✅ 升级测试 + `_evidence_gate` 硬门槛已有测试 |
| W1-5 | 全文证据 → LLM 角色重判（用全文而非 metadata）| ✅ `_judge_external_fulltext_roles`（幂等 + LLM 失败降级 metadata 角色），挂 execute_run `elif verified:` 分支 |
| W1-6 | `resume_discover_runs_for_paper` 等待→恢复流程 | ✅ 已有恢复测试 + 补充 pipeline failed→verification_failed 路径 |
| W1-7 | 验收：机会硬门槛能过 | ⏳ 待真实端到端（343 后端测试）|

### W2 — 机会生成多候选质量

| # | TODO | 状态 |
|---|---|---|
| W2-1 | 主 Case 跑 1-3 次 Discover Run，人工检查多候选区分度 | ⏳ 待真实环境 |
| W2-2 | Critic 反馈注入 OpportunityAgent prompt（challenges 作为约束）| ✅ `_critic_challenges`（narrow/reject 去重≤3）+ `_synthesize_candidates` 新增 `critic_feedback` prompt 约束 + execute_run 第二轮综合合并（去重 title + `critic_refined` 标记）|
| W2-3 | 生成审计字段：prompt_version / model / corpus / 检索快照记入 run | ✅ `DISCOVER_PROMPT_VERSION="discover-v2"` + `_corpus_snapshot`（`workspace-v1-Np-Mk` 指纹，create_run + execute_run preflight 刷新）|
| W2-4 | Unsupported 主张检查（目标 ≤20%，可暂缓）| ⏳ 可暂缓（计划标注）|
| W2-5 | 验收：2-3 个有区分度候选 | ⏳ 待真实端到端（349 后端测试）|

### W3 — Evidence Passport 证据可信度

| # | TODO | 状态 |
|---|---|---|
| W3-1 | `EvidenceManifest` schema：支持/限定/反驳/相似数量 + 独立/全文论文数 + metadata/fulltext 区分 + 版本 + 人工状态 | ✅ |
| W3-2 | Chat / Opportunity / Plan / AgentArtifact 复用同一套证据语义 | ✅ Opportunity；schema 通用 |
| W3-3 | 一致性检查：`[E1]` 引用必须存在 / 无引用标 unsupported / 版本过期标 stale | ✅ 引用存在性 + grounded 无引用；stale 版本检查 ⏳ |
| W3-4 | 前端可信度卡片（覆盖/全文来源/反证状态/外部核验/人工状态）| ✅ |
| W3-5 | 验收：关键结论一键回原文高亮；非法引用被拦截或警告 | ✅ 前端告警 + 回原文已有 |

### W4 — 前端 agent 呈现 + 可信度卡片

| # | TODO | 状态 |
|---|---|---|
| W4-1 | Discover run 详情展示 agent 交接流（基于 `AgentStep`）| ☐ |
| W4-2 | 机会详情加 Evidence Passport 卡片 | ☐ |
| W4-3 | W3 一致性检查的前端告警（unsupported/stale）| ☐ |
| W4-4 | 验收：agent 交接 + 可信度卡片可见 | ☐ |

### W7 — 全生命周期 agent

| # | TODO | 状态 |
|---|---|---|
| W7-1 | AnalyzeAgent：输入实验结果 JSON → 对照证伪标准 → 结论 + 证据引用 | ✅ `_execute_analyze`：verdict(支持/部分支持/否定/证据不足) + conclusion + evidence_refs；产物 `analysis`/`research_memo.md`；结果吃手动数据 |
| W7-2 | WriteAgent：计划+证据 → 章节草稿（Abstract/Intro/Method/Experiments）| ✅ `_execute_write`：title/abstract/intro/method/experiments/conclusion + [En] 回链；产物 `paper_draft`/`paper_draft.md` |
| W7-3 | RespondAgent：论文 + 审稿意见 → 逐条回复草稿 | ✅ `_execute_respond`：`reviewer_comments` → 逐条 response + evidence_refs；产物 `rebuttal`/`rebuttal.md` |
| W7-4 | 数据模型 + 前端入口（挂 plan / opportunity + Evidence Passport）| ✅ 零迁移（context_snapshot/metadata_payload 存 research_plan_id）；ChatComposer 加 3 mode + plan Select；ChatAgentRunCard 多态渲染 md 产物；agent_type Literal 扩展（后端+前端）|
| W7-5 | 验收：确认计划→模拟实验→分析→论文草稿→审稿回复一条链 | ⏳ 代码层完成（354 后端测试 + 5 lifecycle 测试），真实 LLM 一条链待环境 |

### W5 — 端到端验收 + 失败降级

| # | TODO | 状态 |
|---|---|---|
| W5-1 | HITL 4 决策 × API 测试（确认/编辑确认/拒绝/延后）| ✅ `test_discover_hitl.py` 5 个（4 决策 × API + HumanDecision/Timeline 断言）；修了 `HumanDecision.created_at` SQLite 兼容（Python 侧 default，schema 不变）|
| W5-2 | 4 决策 × UI 走查 | ✅ 代码层已就绪（DiscoverPage 决策 modal + 编辑确认 + convert），真实走查待环境 |
| W5-3 | Timeline 追溯验证（决策历史可回溯）| ✅ 每决策断言 timeline 事件 + HumanDecision 记录 + 历史顺序 |
| W5-4 | 四类降级演练：S2 429 / LLM 超时 / Milvus 不可用 / PDF 下载失败 | ✅ 已有覆盖（external_queries 429 / _BoomLLM / retrieval_lifecycle Milvus boom / fulltext PDF）+ 补 execute_run 幂等 + synthesis fallback |
| W5-5 | 多智能体降级：某 agent 失败 → Orchestrator 降级继续 | ✅ critic/role/synthesis LLM 失败降级（已有 + `test_discover_resilience.py` synthesis→rule_based_fallback）|
| W5-6 | 重复点击幂等（spawn idempotency key）| ✅ execute_run terminal 幂等（`test_discover_resilience.py`）+ `_persist_candidates` 幂等 |
| W5-7 | 验收：正常 + 降级路径都跑通 | ⏳ 测试层跑通（363 后端），真实环境端到端待做 |

### W6 — 封版 + 演示预演

| # | TODO | 状态 |
|---|---|---|
| W6-1 | 冻结版本清单：语料 / 标注 / Prompt / 模型 / 解析器 / Schema | ☐ |
| W6-2 | 3 次全新数据库端到端演练 | ☐ |
| W6-3 | 记录解析/抽取/检索/发现的耗时、错误率、token 成本 | ☐ |
| W6-4 | 演示脚本打磨（agent 交接 + 证据回链 + 可信度卡片）| ☐ |
| W6-5 | 验收：演示可复现 | ☐ |

---

## 状态更新记录

| 日期 | 内容 |
|---|---|
| 2026-08-06 | v1 规划稿；多智能体对齐题目 + 全生命周期补全（MA + W1-W7）|
| 2026-08-08 | v2：合入 PR #15（Agent 框架 / Workspace RAG / 研究中心 / Discover 修复）；MA 改为复用 AgentRun/Step/Artifact 拆分 Discover；纳入 zwx P0-1（readiness）与 P0-2（Evidence Passport）为 W0/W3；284 测试基线 |
| 2026-08-09 | MA 多智能体（AgentStep 交接流 + Critic + 收窄）完成；W3 Evidence Passport 完成；**W0 研究准备度完成**（`WorkspaceReadinessService` 五维 + `GET /readiness` 端点 + 前端进度条 + Overview/Dashboard 单一来源计数，333 后端测试）|
| 2026-08-09 | **W1 外部全文核验代码层完成**：`_normalize_pdf_url`（http://→https、arxiv abs→pdf）+ `_judge_external_fulltext_roles`（全文角色重判，幂等+降级）+ evidence_level 升级/resume/failed 路径测试；343 后端测试。真实 OA 端到端（W1-1/2/7）待环境 |
| 2026-08-09 | **W2 机会质量代码层完成**：`_critic_challenges` + `_synthesize_candidates` critic_feedback 注入 + execute_run 第二轮综合（Critic 挑战→重新综合）；`DISCOVER_PROMPT_VERSION` + `_corpus_snapshot` 审计字段；349 后端测试。真实跑（W2-1/5）待环境 |
| 2026-08-09 | **W7 全生命周期 agent 代码层完成**：Analyze/Write/Respond 三 agent（复用 AgentRun/Step/Artifact，`succeeded` 终态 + 证据回链 [En]，零迁移）+ ChatComposer 3 mode + ChatAgentRunCard 多态渲染；354 后端测试 + 5 lifecycle 测试 + 前端 26 测试。真实 LLM 一条链待环境 |
| 2026-08-09 | **W5 端到端/降级代码层完成**：HITL 4 决策 × API + Timeline/HumanDecision 追溯（修 `HumanDecision.created_at` SQLite 兼容）+ 四类降级验证 + execute_run 幂等 + synthesis fallback；363 后端测试。真实环境端到端待做 |
