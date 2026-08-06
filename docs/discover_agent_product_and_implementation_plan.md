# GapMind Discover Agent 现状分析、产品交互与实施规划

> 文档状态：可执行规划
> 编写日期：2026-07-30
> 适用仓库：`D:\A_python_program\GapMind`
> 目标：供后续 Codex 任务直接按阶段实施
> 产品语义优先级：`mvp_core_spec.md` > `mvp_acceptance_and_sequence.md` > `plans.md` > 历史 API/Onboarding 文档

---

## 状态更新（2026-08-06）

> **Retrieval Gate：minimal gold set 已通过，完整 Gate 待语料扩充。**
>
> - 技术链路：RG-2..7 全部完成（来源排除 / 评测框架 / Similar Work 聚合 / Counter 角色排序 / 索引生命周期 / V4 专项）
> - minimal gold set（9 篇 GNN explanation 论文，workspace `123100ea`）完整版带 judge 实测：
>   Semantic/Similar/Counter Recall@10 = **1.0/1.0/1.0**，leakage = **0**（2026-08-06，`evaluation/retrieval/reports/minimal-gnn-v1_*.json`）
> - 抽取质量：RG-1 人工审查回链 100% 精确；P0 精确去重已实现（claim/limitation 同 span 碰撞）
> - 生产 bug 已修：deepseek-v4-flash reasoning 烧光 token → `disable_thinking` 参数
> - **仍待做**：完整 5 case / 12 篇 demo corpus 的正式 Gate（需扩 corpus 缺 GraphFramEx/GOOD/Zorro/OOD-GNN + 补检索 relevance 标注）；之后才能进入 Stage 3 外部核验 / Stage 4 Opportunity 正式生成
> - 完整功能状态见 `docs/functional_roadmap.md`

---

## 0. 给后续执行任务的使用说明

后续任务开始时，应先完整阅读：

1. 仓库和上级目录中的 `AGENTS.md`；
2. 本文档；
3. `docs/mvp_core_spec.md`；
4. `docs/mvp_acceptance_and_sequence.md`；
5. `docs/phase3_smoke_validation_and_next_plan.md`；
6. 当前 `git status`、相关 diff 和当前数据库迁移状态。

执行约束：

- 当前工作区已有未提交的 Knowledge、Discover、Graph 和 Evidence 相关实现；不得覆盖、回退或清理这些用户变更。
- 当前 `0009_mentions_reviews_opportunities.py` 可能已经在本地数据库执行过。不要重写或删除既有迁移；完整 Discover 数据模型使用后续迁移增量演进。
- 不要把当前同步原型直接包装成“正式完成的 Discover Agent”。
- 严格按本文 Gate 顺序实施。前一阶段质量 Gate 未满足时，不宣称后一阶段完成。
- 每完成一个阶段，先运行该阶段测试并汇报结果，再进入下一阶段。
- 若发现迁移实际状态、外部 PDF 自动导入策略或现有产品语义与本文冲突，先向用户说明证据并询问，不自行改方向。
- 未经用户明确要求，不创建提交、不推送、不删除已有数据。

---

## 1. 结论摘要

### 1.1 当前处于什么状态

当前代码已经跑通一个 **Discover 技术原型**：

```text
Knowledge Workbench 中选择一条 Claim
→ 点击 “Discover opportunity”
→ 同步执行 Workspace Similar Work / Counter Evidence
→ 调用 DeepSeek 综合，失败时规则降级
→ 保存一个简化 ResearchOpportunity
→ 在右侧 Drawer 展示结果
```

这条原型链路已经证明：

- Discover 路由和服务可以接入现有 FastAPI 模块化单体；
- 现有 Retrieval 能被编排；
- LLM 不可用时可以降级；
- 前端可以从 Claim 触发并展示基础结果；
- 结果可以写入 `research_opportunities` 表。

但按冻结的 MVP 规格判断，**正式的 Discover P0 闭环尚未完成**。主要缺失：

- 异步 Discover Run、运行阶段、进度和历史；
- Topic/Scope 入口与多候选生成；
- 外部文献新颖性核验；
- 至少两篇独立全文证据的硬门槛；
- 完整 Opportunity 契约；
- Opportunity Version、Evidence、HumanDecision；
- confirm / edit-confirm / reject / defer；
- confirmed Opportunity 转 ResearchPlan；
- 独立 Opportunity Workbench；
- 证据原文回链和完整失败/降级语义。

因此，当前准确状态应表述为：

> Claim 驱动的同步 Discover 原型已完成；Evidence-grounded Opportunity Discovery 的产品闭环尚未完成，不应视为原 Phase 5 已交付。

### 1.2 是否应该有“前端对话框”

答案是：**应该有对话框，但不应该把通用 Chatbot 对话框作为主产品形态。**

推荐三层前端承载：

1. **Discover Run 配置 Modal**
   用于输入 Topic、研究问题、范围、约束、论文范围和生成数量。它是“启动任务”的对话框。

2. **独立 Discover Workbench 页面**
   用于展示异步进度、运行历史、多个 Opportunity、证据、相似工作、反证和人工决策。它是主界面。

3. **Evidence Drawer / Claim 快捷 Drawer**
   从 Knowledge Claim 或 Opportunity 中快速查看证据和启动预填充 Run。它是辅助界面。

不建议 P0 直接实现自由聊天，原因是：

- Discover 是有审计要求的研究任务，不是一次性问答；
- 输出需要版本、证据、状态和用户决策，聊天消息难以表达这些领域对象；
- 长任务需要可恢复、可重试、可回看，而不是依赖当前页面内存；
- GapMind 的定位明确不是“普通 RAG + Chatbot”；
- 自由聊天容易让用户误以为自然语言回答已经成为可信研究结论。

如果需要“对话感”，P0 应采用 **引导式输入 + 结构化追问 + 版本化 Refinement**：

- “把范围限制到 inductive setting”
- “只看 2022 年后的工作”
- “提高可行性，限定单卡 GPU”

每次 Refinement 都必须创建新 Run 或新 Opportunity Version，不能只生成不可追溯的聊天消息。

---

## 2. 原有规划是什么

### 2.1 冻结的 P0 闭环

原规划的主链路是：

```text
研究主题 / 用户论文
→ PDF 解析与证据文本
→ 论文级结构化知识
→ Workspace Retrieval
→ 外部文献候选核验
→ Research Opportunity Proposal
→ 用户确认 / 编辑 / 拒绝 / 延后
→ Research Question / Hypothesis / Validation Plan
```

关键产品原则：

- Workspace 是研究上下文边界，不是新颖性边界；
- Discover 必须主动检索 Workspace 之外的文献；
- metadata-only 只能用于候选筛选，不能单独支撑关键结论；
- Opportunity 至少需要两篇独立论文的全文证据；
- 必须展示 similar work 和 counter evidence；
- 结果只能先成为 candidate；
- Agent 只能提出 Proposal，用户决策后才能生效；
- confirmed / edited_confirmed 才能转换为 ResearchPlan。

### 2.2 原规划的 Discover 运行方式

历史 API 规划明确要求：

```text
POST /workspaces/{workspace_id}/discover/run
→ 202 Accepted
→ task_id
→ 查询 Discover Run 历史和详情
→ 一次 Run 生成多个 Opportunity
```

也就是说，原本规划的是 **异步、可追踪、多候选的 Agent Run**，不是当前的一次同步 POST。

### 2.3 原规划的前端定位

原规划虽然没有给出详细线框图，但明确包含：

- 用户点击 `Run Discover`；
- 查看 Opportunity Candidate；
- Accept / Edit / Reject / Defer；
- 从 Evidence 回到论文原文；
- confirmed Opportunity 生成 Research Plan；
- 独立 Opportunity Workbench；
- Timeline 记录生成、查看、决策和转换。

原规划没有要求通用聊天历史。`Conversation` 只出现在早期架构讨论问题中，没有进入冻结 P0 规格。

---

## 3. 当前实现完成度

### 3.1 后端现状

| 能力 | 状态 | 当前实现 | 与目标的差距 |
| --- | --- | --- | --- |
| Discover Domain | 已有原型 | `backend/app/domains/discover/` | 领域模型过于简化 |
| 创建 Opportunity | 已完成原型 | `POST /workspaces/{id}/discover/opportunities` | 同步执行，只生成一个 |
| Opportunity 列表 | 后端已有 | `GET /workspaces/{id}/discover/opportunities` | 前端未使用，路径也未与独立 Opportunity 资源对齐 |
| Claim 输入 | 已完成 | `claim_item_id` 或 `claim_text` | 缺少 Topic、Scope、Constraints、多论文范围 |
| Similar Work | 部分完成 | 有 `paper_id` 时调用 Workspace Retrieval | 仍是 chunk 级，未做论文级聚合和多样性 |
| Counter Evidence | 部分完成 | Workspace Counter Retrieval + Judge | 未排除来源论文，未完整区分角色和失败状态 |
| External Verification | 未完成 | 未接入 Semantic Scholar Discovery 流程 | 违反“Workspace 不是新颖性边界” |
| LLM Synthesis | 已完成原型 | DeepSeek JSON + rule-based fallback | Prompt/模型/语料版本未形成 Agent Run 审计 |
| Opportunity 持久化 | 已完成原型 | `research_opportunities` | 缺少完整字段、Version、Evidence、Decision、Plan |
| HITL | 未完成 | 仅 KnowledgeItem review | Opportunity 无 confirm/edit/reject/defer |
| Timeline | 未接入 | Timeline 基础能力已存在 | Discover 生成和决策没有事件 |
| Task Runtime | 未接入 | Task/Celery 基础能力已存在 | Discover 仍在同步 HTTP 中运行 |
| 自动化测试 | 极少 | 一个 fallback happy-path 测试 | 缺少独立 domain/API/state/failure 测试 |

### 3.2 当前 Opportunity 数据模型

当前只保存：

- `title`
- `summary`
- `rationale`
- `suggested_directions`
- `confidence`
- `status`
- `source_payload`

冻结规格要求但当前缺少：

- `problem_statement`
- `research_scope`
- 规范化 `supporting_evidence`
- `similar_work`
- `counter_evidence`
- `why_existing_work_is_insufficient`
- `candidate_research_question`
- `candidate_hypothesis`
- `candidate_validation_plan`
- `open_risks`
- `novelty_score`
- `feasibility_score`
- `significance_score`
- `evidence_coverage`
- `verification_status`
- `agent_run_id`
- Prompt / model / corpus / retrieval snapshot 版本
- 不可变 Opportunity Version
- HumanDecision

当前把 Retrieval 全量结果放在 `source_payload`，适合作为原型快照，不适合作为正式可查询、可版本化的证据关系。

### 3.3 Retrieval 现状与阻塞项

当前 Retrieval 技术路径已经存在，但尚未达到进入正式 Opportunity 生成的质量 Gate：

- Similar Work 能排除目标 `paper_id`，但返回的是 chunk 列表，不是 paper-level 结果；
- Counter Evidence 没有 `source_paper_id` / `exclude_paper_ids`，可能返回 Claim 来源论文自身；
- Counter Evidence 尚未按 `contradicts → qualifies → overlaps/supports → unknown` 进行清晰分组；
- “检索成功但未发现”与“检索/Judge 失败”的前端表达不足；
- 未完成正式 Retrieval Gold Set 和 Recall@10 Gate；
- 未完成外部新颖性检索；
- 未完成外部 metadata-only / full-text 的产品展示和 Gate。

`docs/phase3_smoke_validation_and_next_plan.md` 的当前结论仍然是：

> Retrieval 技术 Smoke 通过；质量 Gate 尚未正式通过；暂不进入 Opportunity Discovery 正式生成。

因此后续实现不能跳过 Retrieval 和 External Verification 加固。

### 3.4 前端现状

当前前端已有：

- Workspace → Knowledge 入口；
- Knowledge Workbench；
- Claim 详情 Drawer；
- Claim 上的 `Discover opportunity` 按钮；
- Discover 结果 Drawer；
- 标题、置信度、Claim、Summary、Rationale、方向；
- Similar Work / Counter Evidence 简单列表。

当前前端缺少：

- Workspace 顶层 Discover 入口；
- `/workspaces/:id/discover` 页面；
- Topic/Scope 输入；
- Run 配置和预检；
- Run 进度、阶段、取消、重试；
- Run 历史；
- 已保存 Opportunity 列表；
- 页面刷新后恢复当前结果；
- 多候选比较；
- Opportunity 详情页；
- Evidence 原文定位；
- source_scope / evidence_level；
- verification incomplete；
- confirm / edit-confirm / reject / defer；
- Opportunity Version / diff；
- Generate Plan；
- Timeline 回链；
- 前端 Discover 组件测试。

当前 Drawer 还有两个具体交互问题：

1. 点击按钮立即执行 POST，没有确认范围和配置，容易误触发昂贵任务；
2. 结果只保存在 React 本地 state，关闭页面或刷新后无法从前端恢复，虽然后端已经写入数据库。

### 3.5 当前验证证据

本次分析中已验证：

- `npm run typecheck`：通过；
- `npx vitest run`：1 个测试文件、2 个测试通过；
- `git diff --check`：通过。

当前终端没有可直接使用的项目 Python 解释器，因此本次没有重新运行后端测试。后续执行任务必须先找到正确虚拟环境，再以当前代码重新验证，不能只引用历史测试结果。

---

## 4. 产品信息架构

### 4.1 推荐路由

```text
/workspaces/:workspaceId
├── Workspace Overview
├── /knowledge
├── /knowledge/graph
├── /discover
│   ├── Discover Run history
│   ├── Active Run
│   └── Opportunity candidates
├── /opportunities/:opportunityId
└── /plans/:planId
```

P0 必须增加：

- `/workspaces/:id/discover`
- `/workspaces/:id/opportunities/:opportunityId`

ResearchPlan 页面可以在 HITL 完成后增加。

### 4.2 入口设计

提供三个入口：

#### 入口 A：Workspace 顶部主入口

在 Workspace Detail 顶部操作区增加：

```text
[Knowledge] [Discover] [Refresh]
```

进入 Discover Workbench，不立即创建 Run。

#### 入口 B：Knowledge Claim 快捷入口

保留当前 Claim 上的按钮，但改为：

```text
[Use in Discover]
```

点击后打开 Discover Run Modal，并预填：

- `claim_item_id`
- Claim 文本只读预览
- 来源 Paper
- 默认排除来源 Paper

不要点击后立即生成。

#### 入口 C：Opportunity / Timeline 回链

- Timeline 的 `opportunity.generated`、`opportunity.confirmed` 等事件可跳转详情；
- Workspace Overview 显示待处理 Opportunity 数和最近一次 Discover Run。

---

## 5. 前端页面与交互设计

### 5.1 Discover Run 配置 Modal

标题：

```text
Run Discover
```

字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| Research topic / question | TextArea | Topic 与 Claim 至少一个 | 用户自然语言目标 |
| Seed claim | Claim selector | 否 | 从 Knowledge Claim 预填 |
| Papers in scope | Multi-select | 否 | 默认当前 Workspace 全部已索引论文 |
| Keywords | Tag input | 否 | 从 Workspace Profile 预填 |
| Constraints | TextArea | 否 | 算力、数据、时间、领域限制 |
| Year range | Range | 否 | 外部检索过滤 |
| Max opportunities | Select | 是 | P0 默认 3，上限 5 |
| Include counter evidence | Switch | 是 | 默认开启且 P0 不允许关闭正式 Gate |

Modal 底部展示 Preflight：

```text
Workspace papers: 12
Parsed: 10
Indexed: 9
Knowledge extracted: 8
Human-confirmed claims: 3
External search: available / unavailable
```

提交按钮状态：

- `Run Discover`：满足最小输入；
- `Fix prerequisites`：没有已索引论文或没有可用线索；
- `Run as prototype`：仅开发环境可见，正式环境不展示。

外部 PDF 策略：

- 元数据/摘要检索自动执行；
- P0 默认不静默批量导入所有 PDF；
- 高价值开放 PDF 需要全文核验时，Run 进入 `waiting_for_user`；
- UI 展示候选并让用户选择 `Import and verify`；
- 后续如要默认自动导入，必须单独得到产品确认。

### 5.2 Discover Workbench 桌面布局

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Workspace / Discover                         [New Discover Run]      │
├──────────────────┬───────────────────────────────────────────────────┤
│ Run history      │ Active Run / Selected Run                         │
│                  │                                                   │
│ ● Running        │ Topic + scope + status + progress                 │
│ ✓ Completed      │ [Preflight]—[Local]—[External]—[Verify]—[Synthesize]│
│ ! Needs input    │                                                   │
│ × Failed         │ Opportunity candidates                            │
│                  │ ┌───────────────────────────────────────────────┐ │
│ Filters          │ │ Candidate card                                │ │
│ Date / status    │ │ Evidence coverage / verification / user state │ │
│                  │ └───────────────────────────────────────────────┘ │
└──────────────────┴───────────────────────────────────────────────────┘
```

左栏：

- Run 创建时间；
- Topic/Claim 摘要；
- 状态图标；
- 进度；
- Opportunity 数；
- 需要用户操作时高亮。

主区：

- Run Overview；
- 阶段进度；
- 降级/失败信息；
- 候选 Opportunity 卡片；
- 外部候选选择区；
- Empty/Needs Evidence 状态。

### 5.3 Run 进度展示

固定阶段：

1. `Preflight`
2. `Workspace evidence`
3. `Similar work`
4. `External verification`
5. `Full-text evidence`
6. `Synthesis`
7. `Saved`

每个阶段状态：

- pending
- running
- succeeded
- degraded
- failed
- waiting_for_user
- skipped

不要只显示一个 Spin。至少展示：

- 当前阶段；
- 已处理数量；
- 失败是否可重试；
- 是否需要用户导入全文；
- 已完成阶段不因刷新丢失。

### 5.4 Opportunity Candidate 卡片

卡片首屏只展示决策所需的摘要：

- Title；
- 一句话 Problem Statement；
- User status；
- Verification status；
- Evidence coverage；
- Novelty / Feasibility / Significance；
- 独立全文论文数；
- Similar Work 数；
- Counter / Qualifying Evidence 数；
- `Open details`。

不要把所有长证据直接展开在列表中。

状态必须分为三类，不能混成一个 Confidence：

| 类型 | 示例 |
| --- | --- |
| 模型判断 | Agent confidence 68% |
| 证据质量 | 3 full-text papers · coverage 82% |
| 用户决策 | Candidate / Confirmed / Deferred |

### 5.5 Opportunity 详情页

页面分为六个区：

#### A. Overview

- Title
- Problem Statement
- Research Scope
- Why Existing Work Is Insufficient
- Open Risks
- 三类状态

#### B. Evidence

- Supporting Evidence
- 每条 Evidence 显示 Paper、原文片段、关系、证据等级
- `Open source` 定位到 EvidenceSpan

#### C. Similar Work

- 以 Paper 为主实体；
- 每篇 Paper 只展示一个主摘要和 1–2 个代表性片段；
- 明确说明它与 Opportunity 的重叠点和差异点；
- metadata-only 必须显著标注。

#### D. Counter Evidence & Risks

按顺序分组：

1. Contradicts
2. Qualifies
3. Overlaps / Supports
4. Unknown

空状态必须区分：

- `Search completed; no counter evidence found`
- `Verification incomplete`
- `Retrieval failed`
- `Judge unavailable`

#### E. Proposed Validation

- Candidate Research Question
- Falsifiable Hypothesis
- Datasets / Baselines / Metrics
- Validation Steps
- Expected Supporting Result
- Falsification Criteria
- Resource Constraints

#### F. History

- Discover Run；
- Opportunity Versions；
- Human Decisions；
- Timeline Events；
- ResearchPlan 链接。

### 5.6 Evidence Inspector

点击 Evidence 后使用右侧 Drawer：

- Paper 标题、年份、来源；
- Workspace / External；
- Full text / Metadata only；
- Supports / Qualifies / Contradicts；
- 原始片段；
- 前后文；
- section；
- 证据定位；
- `Open paper` / `Download artifact`。

Evidence Drawer 可以复用现有 `EvidenceViewer`，但需要扩展支持 Retrieval 和 External Evidence。

### 5.7 HITL 操作区

详情页底部使用 Sticky Action Bar：

```text
[Reject] [Defer] [Edit & Confirm] [Confirm]
```

行为：

- `Confirm`：确认当前不可变 Version；
- `Edit & Confirm`：打开结构化编辑 Modal，保存新 Version，再确认；
- `Reject`：可选原因，记录 HumanDecision；
- `Defer`：可选复查条件/日期；
- `Generate Plan`：仅 confirmed / edited_confirmed 显示。

必须做防误操作：

- Decision 提交前显示正在确认的 Version；
- Edit 使用 `base_version_id` 做并发校验；
- 版本冲突返回 409，前端提示刷新；
- reject/defer 后不自动生成 Plan；
- 所有操作成功后刷新详情和 Timeline。

### 5.8 Refinement，而不是自由聊天

P0 可以在 Opportunity 详情增加：

```text
[Refine this opportunity]
```

打开一个小型 Modal：

- refinement instruction；
- 保留/排除哪些证据；
- 范围变化；
- 是否重新执行外部验证。

提交结果必须是：

- 新 Discover Run；或
- 新 Opportunity Version。

禁止：

- 只在前端追加一条 assistant message；
- 覆盖旧 Opportunity；
- 未记录 Evidence 变化；
- 把自由聊天答案直接标记 confirmed。

### 5.9 移动端

在宽度小于 768px 时：

- Run history 改为顶部 Select / Sheet；
- 主内容单列；
- Opportunity 卡片不横向滚动；
- Evidence Drawer 使用全屏；
- Sticky Action Bar 分两行；
- Modal 使用接近全屏宽度；
- 进度步骤改为纵向；
- 长标题、Paper 名和片段允许换行；
- 主要按钮保持至少 44px 可点击高度。

### 5.10 可访问性与反馈

- 所有状态不能只依赖颜色；
- Loading、Empty、Failed、Degraded、Waiting for user 分别有清晰文本；
- Modal 打开后焦点进入标题或首字段；
- 关闭后焦点回到触发按钮；
- Escape、Tab 和 Shift+Tab 行为正确；
- 异步状态变化使用可感知提示，但不连续刷 Toast；
- 长任务离开页面后继续运行，返回页面可以恢复。

### 5.11 UI 语言

当前项目 UI 主要使用英文。Discover 新页面应继续使用英文 UI 文案，避免局部中英混杂；本文用中文描述产品逻辑。若要切换中文，应作为全局 i18n 任务处理，不在 Discover P0 中单独改。

---

## 6. 后端领域模型规划

### 6.1 迁移策略

新增迁移建议命名：

```text
0010_discover_runs_opportunity_workflow
```

原则：

- 保留现有 `research_opportunities` 和已有数据；
- 新增表和列，逐步把 `source_payload` 原型数据迁移到正式结构；
- 不在迁移中调用外部服务或 LLM；
- 不删除现有字段；
- 先兼容读，完成数据回填和接口切换后再考虑未来清理；
- downgrade 只回退本迁移新增结构，不破坏 `0009`。

### 6.2 DiscoverRun

建议字段：

```text
id
workspace_id
task_id
parent_run_id
trigger_type              # topic | claim | opportunity_refinement
input_topic
input_claim_item_id
input_payload             # scope / constraints / selected papers
config                    # max_opportunities / top_k / switches
status                    # queued / running / waiting_for_user / succeeded / failed / cancelled
stage                     # preflight / workspace_retrieval / external_search / ...
progress
verification_status       # not_started / in_progress / complete / incomplete / failed
retrieval_snapshot_version
prompt_version
model_provider
model_name
model_parameters
corpus_version
error_code
error_message
started_at
finished_at
created_at
updated_at
```

Task 是运行容器；DiscoverRun 是产品和审计对象。不能只把 Discover 状态放在 Task payload 中。

### 6.3 DiscoverExternalCandidate

用于保存每次 Run 的外部搜索快照：

```text
id
discover_run_id
query
rank
external_paper_id
title
authors
year
abstract
open_access_pdf
role                       # similar / overlap / qualify / contradict / unknown
role_confidence
evidence_level             # metadata_only / full_text
verification_status
imported_paper_id
snapshot_payload
created_at
```

要求：

- 外部 API 响应必须按 Run 保存快照；
- metadata-only 不转成伪造 EvidenceSpan；
- 导入并解析后，关联本地 `paper_id` 和全文 EvidenceSpan。

### 6.4 ResearchOpportunity

现有表作为 Opportunity 身份和当前状态：

```text
id
workspace_id
discover_run_id
current_version_id
status
is_deleted
created_at
updated_at
```

为兼容当前原型，可以暂时保留：

- title
- summary
- rationale
- suggested_directions
- confidence
- source_payload

新接口读取应逐步以 Current Version 为准。

### 6.5 OpportunityVersion

每次生成和编辑都创建不可变版本：

```text
id
opportunity_id
version_number
title
problem_statement
research_scope
why_existing_work_is_insufficient
candidate_research_question
candidate_hypothesis
candidate_validation_plan
open_risks
novelty_score
feasibility_score
significance_score
confidence
evidence_coverage
verification_status
synthesis_metadata
created_by                  # agent | user
created_at
```

约束：

- `(opportunity_id, version_number)` 唯一；
- Version 内容不可 update；
- 用户编辑产生新 Version；
- `current_version_id` 指向最新产品版本；
- HumanDecision 永远引用明确 Version。

### 6.6 OpportunityEvidence

建议字段：

```text
id
opportunity_version_id
relation                    # supports / similar / contradicts / qualifies / overlaps
source_scope                # workspace / external
evidence_level              # full_text / metadata_only
paper_id
external_candidate_id
evidence_span_id
artifact_id
chunk_id
rank
score
judgement
judgement_confidence
display_excerpt
snapshot_payload
created_at
```

要求：

- 关键支持结论至少关联两篇独立 `full_text` Paper；
- metadata-only 可以出现在 Similar Work，但不能作为唯一 supporting evidence；
- UI 所需展示信息不能依赖重新调用外部 API；
- 每条证据必须可追溯到本地 EvidenceSpan 或保存的外部快照。

### 6.7 HumanDecision

```text
id
opportunity_id
from_version_id
to_version_id
action                      # confirm / edit_confirm / reject / defer
reason
defer_condition
actor
created_at
```

### 6.8 ResearchPlan

仅 confirmed / edited_confirmed 可创建：

```text
id
workspace_id
opportunity_id
opportunity_version_id
status
research_question
hypothesis
scope_and_assumptions
datasets
baselines
metrics
validation_steps
expected_supporting_result
falsification_criteria
risks
resource_constraints
created_at
updated_at
```

ResearchPlan 也属于 Proposal，后续允许用户编辑；它必须始终引用固定 Opportunity Version。

---

## 7. API 规划

### 7.1 Discover Run

#### 创建 Run

```http
POST /api/v1/workspaces/{workspace_id}/discover/runs
```

请求：

```json
{
  "input": {
    "topic": "Robust self-interpretable GNNs under distribution shift",
    "claim_item_id": null,
    "paper_ids": [],
    "keywords": ["self-interpretable GNN", "distribution shift"],
    "constraints": "Single GPU; public datasets"
  },
  "scope": {
    "year_from": 2020,
    "year_to": 2026,
    "open_access_preferred": true
  },
  "config": {
    "max_opportunities": 3,
    "top_k": 10,
    "include_counter_evidence": true
  }
}
```

响应：

```http
202 Accepted
```

```json
{
  "run_id": "uuid",
  "task_id": "uuid",
  "status": "queued"
}
```

#### Run 列表

```http
GET /api/v1/workspaces/{workspace_id}/discover/runs?status=&limit=&offset=
```

#### Run 详情

```http
GET /api/v1/workspaces/{workspace_id}/discover/runs/{run_id}
```

返回：

- stage/progress/status；
- input/scope/config；
- stage summaries；
- external candidate counts；
- verification status；
- Opportunity summaries；
- task/error；
- versions。

#### 外部候选选择并恢复 Run

```http
POST /api/v1/workspaces/{workspace_id}/discover/runs/{run_id}/external-selection
```

```json
{
  "candidate_ids": ["uuid"],
  "action": "import_and_verify"
}
```

#### 取消 Run

```http
POST /api/v1/workspaces/{workspace_id}/discover/runs/{run_id}/cancel
```

内部复用 Task Runtime 的取消状态机。

### 7.2 Opportunity

#### 列表

```http
GET /api/v1/workspaces/{workspace_id}/opportunities?status=&run_id=&limit=&offset=
```

#### 详情

```http
GET /api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}
```

返回当前 Version、Evidence、Decision 摘要和 Plan 链接。

#### Version

```http
GET /api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}/versions
GET /api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}/versions/{version_id}
```

#### Confirm

```http
POST /api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}/confirm
```

```json
{
  "version_id": "uuid",
  "note": "Evidence checked"
}
```

#### Edit & Confirm

```http
PATCH /api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}
```

```json
{
  "base_version_id": "uuid",
  "action": "edit_confirm",
  "changes": {
    "title": "...",
    "research_scope": "...",
    "candidate_hypothesis": "..."
  },
  "note": "Narrowed the scope"
}
```

`base_version_id` 不是当前版本时返回 `409 Conflict`。

#### Reject

```http
POST /api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}/reject
```

#### Defer

```http
POST /api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}/defer
```

#### 转 Plan

```http
POST /api/v1/workspaces/{workspace_id}/opportunities/{opportunity_id}/convert
```

只有 confirmed / edited_confirmed 可执行。生成如果需要 LLM，应返回 `202 + task_id`；不能在同步请求中执行长调用。

### 7.3 错误契约

错误响应统一包含：

```json
{
  "detail": {
    "error": "stable_error_code",
    "message": "Safe user-facing message",
    "retryable": true,
    "stage": "external_search"
  }
}
```

至少定义：

- `discover_preflight_failed`
- `insufficient_full_text_evidence`
- `external_verification_incomplete`
- `retrieval_failed`
- `judge_degraded`
- `opportunity_version_conflict`
- `invalid_opportunity_transition`
- `plan_requires_confirmed_opportunity`

---

## 8. Discover Agent 编排

### 8.1 状态流

```text
queued
→ running / preflight
→ running / workspace_retrieval
→ running / similar_work
→ running / external_search
→ waiting_for_user / external_selection
→ running / fulltext_verification
→ running / synthesis
→ running / persisting
→ succeeded

任意阶段
→ degraded（允许继续但必须标记）
→ failed（无法满足安全 Gate）
→ cancelled
```

### 8.2 Preflight

检查：

- Workspace 存在且未归档；
- 至少有 Topic 或 Claim；
- Claim 属于当前 Workspace；
- 选中 Paper 属于当前 Workspace；
- Paper parse/index/extract 状态；
- Retrieval 依赖状态；
- 外部检索可用性；
- LLM 可用性；
- 是否满足最小生成条件。

Preflight 结果保存到 Run，不只写日志。

### 8.3 Workspace Evidence

必须先完成 Retrieval 加固：

- Counter Evidence 支持 `source_paper_id` / `exclude_paper_ids`；
- Recall 阶段尽早排除来源论文；
- 返回 `filters_applied`；
- Similar Work 按 Paper 聚合；
- 每篇 Paper 保留代表性 chunk；
- 做 Paper diversity；
- Counter 按角色分组；
- 区分 succeeded empty / degraded / failed。

### 8.4 External Verification

复用现有：

- `SemanticScholarClient`
- 搜索缓存；
- 限流；
- 重试；
- Open Access PDF；
- arXiv fallback；
- Paper 导入和解析 pipeline。

不要从 Agent Service 调用自己的 HTTP Router；应抽取并复用 Gateway/Domain Service。

保存：

- query；
- filters；
- 检索时间；
- Semantic Scholar candidate；
- rank；
- role judgement；
- metadata/full-text 状态；
- 失败/降级原因。

### 8.5 Full-text Gate

正式生成单个 Opportunity 前：

- 至少两篇独立 Paper；
- Supporting Evidence 为 full-text；
- 每条关键判断有 EvidenceSpan；
- Similar Work 已检查；
- Counter Evidence 已检查，或明确记录未发现/失败；
- External Verification 至少执行一次；
- metadata-only 不作为唯一支持。

不满足时：

- Run 可以 `succeeded` 但结果为 `needs_more_evidence`，不创建合格 Opportunity；或
- Run 进入 `waiting_for_user` 请求导入全文。

禁止为了“总要生成点东西”而绕过 Gate。

### 8.6 Synthesis

LLM 输入：

- Workspace context；
- Claim/Topic；
- Supporting Evidence；
- Similar Work；
- Counter/Qualifying Evidence；
- User constraints；
- 明确的数据版本。

输出必须通过严格 Pydantic Schema，不使用宽松字符串兜底伪装成合格结果。

规则降级可以：

- 生成 `prototype` / `verification_incomplete` 草案；
- 提示需要更多证据；
- 提供下一步检索建议。

规则降级不可以：

- 在不满足证据 Gate 时创建正式可确认的 Opportunity；
- 使用高 confidence；
- 声称新颖性已验证。

### 8.7 持久化与事务

- Run、Opportunity、Version、Evidence 在明确事务边界内保存；
- Timeline 事件与业务状态一致；
- LLM/外部调用不持有长数据库事务；
- worker 重试必须幂等；
- 同一个 Run 重试不能重复创建 Opportunity；
- 使用稳定的 idempotency key，例如 `run_id + candidate_index + synthesis_version`。

---

## 9. Timeline 事件

至少增加：

```text
discover.run_created
discover.run_started
discover.external_input_requested
discover.run_completed
discover.run_failed
opportunity.generated
opportunity.viewed_evidence
opportunity.confirmed
opportunity.edited_confirmed
opportunity.rejected
opportunity.deferred
plan.generated
```

每个事件包含：

- subject type/id；
- run_id；
- version_id；
- actor；
- 可安全展示的摘要；
- 跳转所需 ID；
- 不包含 API Key、完整 Prompt 密钥或敏感错误堆栈。

---

## 10. 前端代码结构规划

### 10.1 新增页面

```text
frontend/src/pages/DiscoverPage.tsx
frontend/src/pages/OpportunityDetailPage.tsx
frontend/src/pages/ResearchPlanPage.tsx              # HITL 后实施
```

### 10.2 新增组件

```text
frontend/src/components/discover/DiscoverRunModal.tsx
frontend/src/components/discover/DiscoverRunHistory.tsx
frontend/src/components/discover/DiscoverRunProgress.tsx
frontend/src/components/discover/DiscoverPreflight.tsx
frontend/src/components/discover/ExternalCandidateSelection.tsx
frontend/src/components/discover/OpportunityCard.tsx
frontend/src/components/discover/OpportunityStatus.tsx
frontend/src/components/discover/OpportunityActions.tsx
frontend/src/components/discover/OpportunityEditModal.tsx
frontend/src/components/discover/EvidenceInspector.tsx
frontend/src/components/discover/RefineOpportunityModal.tsx
```

### 10.3 API 与类型

```text
frontend/src/api/discover.ts
frontend/src/api/opportunity.ts
frontend/src/api/researchPlan.ts
frontend/src/api/types/discover.ts
frontend/src/api/types/opportunity.ts
```

当前 `frontend/src/api/discover.ts` 的类型缺少：

- `source_scope`
- `evidence_level`
- `artifact_id`
- `section`
- `filters_applied`
- Run/Version/Decision/Plan 类型

需要按后端 schema 一次性对齐，避免在组件中使用 `Record<string, unknown>` 解析核心业务对象。

### 10.4 现有组件处理

当前 `DiscoverOpportunity.tsx` 不直接删除：

- 第一阶段改名或重构为 Claim 快捷入口；
- 点击后打开 `DiscoverRunModal`；
- 结果展示迁移到 Discover/Opportunity 页面；
- 若保留 Quick Preview，只读取已保存 Opportunity，不再维护唯一结果 state。

现有 `EvidenceViewer.tsx`：

- 提取通用 Evidence Inspector 能力；
- 支持 Knowledge EvidenceSpan 和 OpportunityEvidence；
- 支持 metadata-only 的只读快照展示；
- 支持移动端全屏。

### 10.5 前端状态管理

P0 不需要为 Discover 引入新的全局状态库模式。优先：

- URL 保存 selected run/opportunity；
- API 是事实来源；
- 局部表单 state 留在组件；
- 轮询 Task/Run 时复用统一 hook；
- 页面刷新后通过 URL/API 恢复；
- 不把长任务结果只存在 Zustand 或组件 state。

建议 hook：

```text
useDiscoverRuns(workspaceId)
useDiscoverRun(workspaceId, runId)
useRunPolling(runId)
useOpportunity(workspaceId, opportunityId)
```

轮询策略：

- running：1.5–2 秒；
- waiting_for_user：停止高频轮询；
- terminal：停止；
- 页面不可见时降低频率；
- 请求失败使用有限退避，不无限刷错误提示。

---

## 11. 分阶段实施顺序

### Phase 0：保护现有工作并建立基线

任务：

1. 阅读说明和当前 diff；
2. 确认 `0009` 是否已应用到任何保留数据库；
3. 记录当前未提交文件；
4. 找到正确 Python 环境；
5. 运行现有 backend/frontend tests；
6. 把当前 Claim → Drawer 原型行为记录为 baseline；
7. 不修改业务代码。

完成条件：

- 有当前测试结果；
- 有迁移状态；
- 明确哪些文件是用户已有变更；
- 失败测试先分类为历史失败或当前回归。

### Phase 1：Retrieval Gate 加固

任务：

1. Counter Evidence 增加来源排除；
2. `filters_applied` 完整返回；
3. Similar Work 论文级聚合；
4. Paper diversity；
5. Counter role 排序；
6. 空结果/失败/Judge 降级语义；
7. 后端 contract tests；
8. 建立或接入 Retrieval Gold Set；
9. 运行 Recall@10、MRR、diversity、workspace leakage。

Gate：

- Semantic Search Recall@10 ≥ 0.80；
- Similar Work Recall@10 ≥ 0.80；
- Counter Evidence Recall@10 ≥ 0.70；
- workspace leakage = 0；
- source paper leakage = 0；
- 所有结果可回链。

未通过时：

- 可以继续建设 Discover 页面壳和 Run 基础；
- 不允许正式批量生成 Opportunity；
- UI 必须显示 Prototype / Verification incomplete。

### Phase 2：External Verification

任务：

1. 抽取 Semantic Scholar 可复用 service；
2. 从 Topic/Claim 构造外部 query；
3. 保存外部 candidate snapshot；
4. role judgement；
5. metadata-only/full-text 区分；
6. 用户选择 OA PDF；
7. 导入、解析、索引、抽取；
8. 失败/限流/无 PDF 降级；
9. 外部验证测试。

Gate：

- 每个正式 Opportunity 前至少一次外部检索；
- 主 Case 的 gold similar/counter candidate 可在 Top 10 召回；
- metadata-only 不承担关键支持；
- API 失败时 Run 明确 incomplete；
- 外部候选快照可复现。

### Phase 3：Discover 数据模型与 API

任务：

1. 新增 `0010` 迁移；
2. DiscoverRun；
3. ExternalCandidate；
4. OpportunityVersion；
5. OpportunityEvidence；
6. HumanDecision；
7. ResearchPlan 基础表；
8. Pydantic schemas；
9. Run/Opportunity API；
10. 兼容当前 `research_opportunities` 数据；
11. migration/API tests。

Gate：

- 全新数据库可从头迁移；
- 已有 `0009` 数据不丢失；
- Version 不可变；
- Workspace 隔离；
- API 契约和错误码稳定。

### Phase 4：异步 Agent 编排

任务：

1. 新增 Celery Discover worker；
2. Run stage/progress；
3. Preflight；
4. Workspace Retrieval；
5. External Verification；
6. waiting_for_user/resume；
7. Full-text Gate；
8. strict synthesis schema；
9. 幂等持久化；
10. Timeline；
11. cancel/retry；
12. worker/service tests。

Gate：

- HTTP 创建返回 202；
- 服务重启/页面刷新不丢 Run；
- 重试不重复创建候选；
- 无 LLM/外部 API 时状态真实；
- 不满足证据 Gate 不创建可确认候选；
- 一次 Run 可生成 1–3 个合格候选。

### Phase 5：Discover Workbench 前端

任务：

1. 增加 Workspace Discover 入口；
2. Run Modal；
3. Discover Page；
4. Run history；
5. Progress；
6. external selection；
7. Opportunity cards；
8. Opportunity detail；
9. Evidence Inspector；
10. 错误/降级/空状态；
11. 响应式；
12. 前端测试。

Gate：

- 刷新后恢复；
- 多 Run 可切换；
- waiting_for_user 可继续；
- 证据层级清晰；
- 所有关键结果可回到证据；
- 移动端可完成主流程；
- 无通用 Chatbot 误导。

### Phase 6：HITL 与 ResearchPlan

任务：

1. confirm；
2. edit-confirm；
3. reject；
4. defer；
5. Version diff；
6. Timeline；
7. confirmed → Plan；
8. Plan 编辑；
9. 状态机测试；
10. 前端操作测试。

Gate：

- 四种决策都有 API/UI/test；
- edit-confirm 保留旧版本；
- reject/defer 不生成 Plan；
- Plan 引用固定 Version；
- 非 confirmed 转换返回稳定错误；
- Demo 可连续完成。

### Phase 7：Benchmark、文档与发布前加固

任务：

1. 更新 `api_reference.md`；
2. 更新 `data_contracts_v1.md`；
3. 更新 `db_schema.md`；
4. 更新 README 阶段状态；
5. 固化 Prompt/model/corpus/retrieval versions；
6. 五个 Opportunity Case；
7. Unsupported Opportunity Rate；
8. Missed Gold Similar Work Rate；
9. Vanilla RAG blind comparison；
10. 三次全新数据库演练；
11. 正常路径和降级路径 Demo。

Gate：

- 五个 Case 均完成；
- Unsupported Opportunity Rate ≤ 20%；
- Missed Gold Similar Work Rate ≤ 20%；
- 至少两名评审者保留独立评分；
- 可展示一个被系统否定/收窄的弱机会；
- 可展示一个编辑确认后生成 Plan 的机会。

---

## 12. 测试规划

### 12.1 Backend 单元测试

Discover Service：

- Topic 输入；
- Claim 输入；
- Claim 不属于 Workspace；
- source paper exclusion；
- Similar Work paper aggregation；
- Counter role sorting；
- external search succeeded/empty/failed/rate-limited；
- metadata-only；
- full-text Gate；
- LLM invalid JSON；
- LLM unavailable；
- idempotent retry；
- multiple opportunities；
- insufficient evidence 不生成正式候选。

状态机：

- allowed transitions；
- invalid transitions；
- confirm；
- edit_confirm new version；
- reject；
- defer/resume；
- superseded；
- plan guard。

### 12.2 Backend API 测试

- Run create/list/detail；
- 202 response；
- workspace isolation；
- pagination/filter；
- waiting_for_user resume；
- cancel；
- opportunity list/detail/version；
- version conflict 409；
- stable error schema；
- Timeline events；
- existing `0009` compatibility。

### 12.3 Worker 测试

- stage progress；
- retry；
- duplicate delivery；
- external timeout；
- LLM timeout；
- database rollback；
- partial external import；
- cancellation；
- resume after waiting_for_user。

### 12.4 Frontend 测试

需要先补齐统一脚本：

```json
"test": "vitest run"
```

组件测试：

- Run Modal validation；
- Claim 预填但不立即 POST；
- progress states；
- waiting_for_user；
- opportunity status separation；
- metadata-only label；
- empty vs failed；
- confirm/edit/reject/defer；
- version conflict；
- mobile Drawer mode；
- polling stops on terminal state。

### 12.5 必跑验证

后端：

```text
pytest -q
alembic heads
alembic upgrade head
python -m compileall -q app
```

前端：

```text
npm run typecheck
npm test
npm run build
```

通用：

```text
git diff --check
```

在当前 Windows 环境中应使用项目实际虚拟环境中的 `pytest` / `alembic`，不要假设 `python -m alembic` 可用。

---

## 13. 可观测性与审计

每个 Run 记录：

- 总耗时；
- 各 stage 耗时；
- Retrieval 数量；
- 独立 Paper 数；
- external candidate 数；
- full-text verified 数；
- LLM provider/model；
- Prompt version；
- token/cost（如果 Gateway 可提供）；
- 降级/失败原因；
- user waiting 时间；
- 生成 Opportunity 数；
- Gate 拒绝原因。

日志要求：

- 统一 `discover.*` event name；
- 使用 run_id/task_id/opportunity_id；
- 不记录 API Key；
- 不把完整论文正文写入普通日志；
- 用户可见错误与内部诊断分离。

---

## 14. 安全与产品边界

P0 不做：

- 多 Agent 辩论；
- 通用科研 Chatbot；
- 自动确认研究结论；
- 自动批量下载所有外部 PDF；
- 自动执行实验；
- GNN Opportunity Ranking；
- 模型微调作为主链路依赖；
- 自动把聊天内容写入 Knowledge；
- 在证据不足时仍输出“已验证的新颖性”。

所有 LLM 输出：

- 初始状态为 candidate；
- 必须带生成和证据版本；
- 必须能被用户拒绝；
- 不能覆盖旧版本；
- 不能绕过 Evidence Gate。

---

## 15. 文件级实施清单

### 15.1 Backend 重点文件

现有需要演进：

```text
backend/app/domains/discover/models.py
backend/app/domains/discover/schemas.py
backend/app/domains/discover/service.py
backend/app/domains/discover/router.py
backend/app/domains/retrieval/schemas.py
backend/app/domains/retrieval/service.py
backend/app/domains/retrieval/router.py
backend/app/domains/paper/search_service.py
backend/app/domains/timeline/service.py
backend/app/db/models.py
backend/app/api/v1/router.py
```

建议新增：

```text
backend/app/domains/discover/state_machine.py
backend/app/domains/discover/gates.py
backend/app/domains/discover/external_verification.py
backend/app/domains/discover/synthesis.py
backend/app/workers/tasks/run_discover.py
backend/tests/test_discover_service.py
backend/tests/test_discover_api.py
backend/tests/test_opportunity_state_machine.py
backend/tests/test_discover_worker.py
backend/alembic/versions/0010_discover_runs_opportunity_workflow.py
```

### 15.2 Frontend 重点文件

现有需要演进：

```text
frontend/src/App.tsx
frontend/src/pages/WorkspaceDetailPage.tsx
frontend/src/api/discover.ts
frontend/src/components/DiscoverOpportunity.tsx
frontend/src/components/EvidenceViewer.tsx
frontend/package.json
```

新增路径见“前端代码结构规划”。

### 15.3 文档

完成实现后更新：

```text
docs/api_reference.md
docs/data_contracts_v1.md
docs/db_schema.md
docs/mvp_acceptance_and_sequence.md
README.md
```

不要让 README 继续显示 Phase 0 current，而实际代码已进入后续阶段。

---

## 16. 最终验收场景

### 场景 A：从 Topic 开始

1. 用户进入 Workspace Discover；
2. 输入 Topic 和约束；
3. Preflight 展示当前语料状态；
4. 创建异步 Run；
5. 查看 Workspace Retrieval；
6. 查看外部候选；
7. 选择 OA PDF 做全文核验；
8. Run 生成 1–3 个候选；
9. 每个候选满足 Evidence Gate；
10. 用户打开证据原文；
11. 用户确认一个候选；
12. 生成可编辑 Plan；
13. Timeline 完整记录。

### 场景 B：从 Claim 开始

1. 用户在 Knowledge Workbench 选中 Claim；
2. 点击 `Use in Discover`；
3. Run Modal 预填 Claim/Paper；
4. 来源 Paper 被排除在 Counter Evidence 之外；
5. 外部新颖性核验完成；
6. 生成 Opportunity；
7. 用户 Edit & Confirm；
8. 旧 Version 保留；
9. Plan 引用新 Version。

### 场景 C：证据不足

1. 只有一篇全文证据；
2. Agent 不创建可确认 Opportunity；
3. Run 显示 `Needs more evidence`；
4. 推荐外部候选；
5. 用户可以导入并继续；
6. 不出现虚高 Confidence。

### 场景 D：外部 API 失败

1. Semantic Scholar 限流或不可用；
2. Run 显示 `External verification incomplete`；
3. Workspace 结果仍可查看；
4. 不声称新颖性完成；
5. 用户可以 Retry；
6. 已完成的本地步骤不重复。

### 场景 E：LLM 失败

1. Retrieval 和 Evidence 已保存；
2. Synthesis 失败；
3. Run 可重试 Synthesis；
4. 不重复外部下载；
5. 规则降级只产生未验证草案或下一步建议；
6. 不创建可确认的假正式 Opportunity。

---

## 17. Definition of Done

只有以下全部满足，才能称 Discover Agent P0 完成：

- [ ] Retrieval 三项质量 Gate 达标；
- [ ] 来源论文排除和 paper-level diversity 达标；
- [ ] 外部新颖性核验接入；
- [ ] metadata-only / full-text 完整区分；
- [ ] Discover Run 异步、可恢复、可追踪；
- [ ] Opportunity 完整契约；
- [ ] 至少两篇独立全文支持证据；
- [ ] Similar Work 和 Counter Evidence 可解释；
- [ ] Prompt/model/corpus/retrieval snapshot 可审计；
- [ ] Opportunity Version 不可变；
- [ ] confirm / edit-confirm / reject / defer 完成；
- [ ] confirmed Opportunity 可生成 ResearchPlan；
- [ ] Discover Workbench 完成；
- [ ] Evidence 可以回到原文；
- [ ] 页面刷新后状态不丢失；
- [ ] 正常、空、降级、失败、等待用户状态清楚；
- [ ] Desktop 和 Mobile 主流程可用；
- [ ] Backend、Frontend、Migration、Build 全部通过；
- [ ] 文档与实现一致；
- [ ] 五个 Benchmark Case 和 Demo Gate 达标。

---

## 18. 推荐给后续 Codex 任务的执行指令

可将下面内容与本文档一起交给后续任务：

```text
请阅读 docs/discover_agent_product_and_implementation_plan.md，并严格按其中的 Gate 顺序执行。

先只读检查当前 git status、AGENTS.md、0009 迁移是否已应用、现有 Discover/Knowledge/
Retrieval 代码和可用 Python 环境。当前工作区包含用户未提交变更，不得覆盖或回退。

先完成 Phase 0 并汇报基线，再从 Phase 1 开始实施。每个 Phase 完成后运行该阶段测试，
说明修改文件、验证结果、剩余风险和是否满足 Gate；没有满足 Gate 时不要擅自进入正式
Opportunity 生成。不要把自由 Chatbot 作为主界面，采用 Run Modal、Discover Workbench
和 Evidence Drawer 的产品结构。未经明确要求不要提交或推送。
```
