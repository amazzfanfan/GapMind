# GapMind 后续功能完善计划（多智能体协同 + 全生命周期）

> 更新日期：2026-08-06
> 状态：规划稿，待评审
> 关联：`functional_roadmap.md`（功能层现状）+ `external_novelty_gate_report.md`（Stage 3 Gate）

---

## 1. 战略目标

比赛提交题目：**基于学科领域大模型与多智能体协同的科研辅助系统**。

当前系统是一个单 Discover 管线（`execute_run` 同步编排检索/外部核验/综合/门），LLM 虽有角色分工但未以"智能体"形态呈现和协调——**与题目承诺的"多智能体协同"存在架构差距**。

本计划的核心目标：
1. **把单管线重构为有界的多智能体协同**（对齐题目，且 demo 可直观展示 agent 交接）；
2. **补全研究全生命周期**（发现→假设→实验规划→结果分析→论文写作→审稿回复），从"找机会"升级为"贯穿研究全程的助理"；
3. 保持 GapMind 核心原则：**一切 LLM 产物回链证据，不成为未验证事实**。

---

## 2. 端到端系统形态（验收基准）

用户走完整研究生命周期：

```
1. 导入论文 → 解析 → 知识抽取（方法/任务/数据集/主张/局限），每条回链原文   [已能]
2. Workspace 检索：语义搜 / 相似工作 / 反证（来源排除 + 角色排序）         [已能，质量中等]
3. Discover Run（多智能体协同）：
   Planner 分解 → Evidence 检索 → ExternalNovelty 外部核验（研究轴 query + 精确名查找）
   → Opportunity 综合 → Critic 挑战 → Gate 校验 →（收窄/否定）→ 多候选机会 [MA 重构后]
4. 外部全文核验：选 OA PDF → 下载 → 解析 → 抽取 → 全文证据回链 → 角色重判   [W1]
5. HITL 决策：确认/编辑确认/拒绝/延后 + Timeline 追溯 + 版本 diff         [已能，W4 补 UI]
6. 研究计划：问题/假设/验证步骤/证伪标准，回链证据                       [已能]
7. 结果分析：上传实验结果 → 对照证伪标准 → 结论                          [W7]
8. 论文写作：机会+计划+证据 → 章节草稿                                    [W7]
9. 审稿回复：审稿意见 → 基于论文+证据的回复草稿                           [W7]
10. 降级路径：S2 429 / LLM 挂 → 系统降级仍可用                           [W5]
11. 封版演示：3 次全新 DB 端到端，冻结版本，记录耗时/错误率/token          [W6]
```

---

## 3. 多智能体架构设计（核心）

### 3.1 Agent 角色

有界的 6-8 个角色 agent，每个 = **角色 prompt + 可调用的现有 service 方法 + 输入/输出**（函数级特化，不引入 agent 框架/消息队列）：

| Agent | 职责 | 复用现有 |
|---|---|---|
| **Orchestrator / Planner** | 分解研究问题 → 规划工作流 → 调度 → 决定下一步（收窄/重试/否定/定稿）| `execute_run` 编排 |
| **EvidenceAgent** | workspace 检索（语义/相似/反证）+ 证据装配 | `_workspace_similar/_counter/_supporting` |
| **ExternalNoveltyAgent** | 外部 query 构造 + S2 检索 + 角色判别 + 全文核验 | `_external_query_plan/_external_verify` |
| **CriticAgent**（新）| 对抗性审查：找反证缺口、挑战假设、检查"是否真的没人做过"→ 输出 challenges + 收窄建议 | 新 LLM 角色 |
| **OpportunityAgent** | 从证据 + Critic 反馈综合机会候选 | `_synthesize_candidates` |
| **GateAgent** | 硬门槛（≥2 独立全文）+ needs_more_evidence 明细 | `_evidence_gate` |
| **PlanAgent** | 确认机会 → 假设 + 验证计划 | 现有 plan 生成 |
| **AnalyzeAgent / WriteAgent / RespondAgent** | W7 全生命周期 | 新（W7）|

### 3.2 Orchestrator 循环

```
Planner 分解
  → [Evidence, ExternalNovelty] 并行收集
  → Opportunity 综合（多候选）
  → Critic 挑战
       ├─ 无 gap → Gate 校验 → PlanAgent
       └─ 有 gap → Orchestrator 决定：
             ├─ 收窄：换角度重试（补证据 / 换检索词）→ 回到 Evidence/ExternalNovelty
             └─ 否定：标记弱机会 + 理由 → 返回用户（demo 亮点"系统主动收窄/否定"）
```

**Critic 循环天然吸收原 W3（自主收窄/重试）**——不再是后补的重试逻辑，而是多智能体协同的产物。

### 3.3 ResearchContext（共享对象）

研究问题 + 证据账本（支持/相似/反证/外部全文，带回链）+ 机会候选（含 Critic 反馈）+ gate 状态 + **agent_log**。

### 3.4 Timeline 集成

每个 agent 开始/完成/交接写 timeline event（`discover.agent.*`），前端展示 agent 交接流。这是 demo 里"多智能体协同"的可视化证据。

### 3.5 领域大模型接入（已对齐）

`gateway/llm.py` 模型无关（`DEEPSEEK_MODEL` 可配）；zf 的 Qwen3:8B+LoRA 微调模型就绪后即插即用。真正差距只有多智能体形态。

---

## 4. 工作流分解

### MA — 多智能体骨架（架构底座，最高优先级）

- **现状**：单管线 `execute_run`，LLM 角色分工未 agent 化
- **工作**：
  1. Agent 抽象 + ResearchContext（新模块 `discover/agents.py`）
  2. Orchestrator 循环（重构 `execute_run`）
  3. CriticAgent（新角色）
  4. agent_log → Timeline（`discover.agent.*`）
  5. 复用现有 service 方法，保持 265 测试绿（或迁移后绿）
- **验收**：主 Case 跑通 agent 协调流程；Critic 挑战 → 收窄/否定可见；Timeline 记录 agent 交接

### W1 — 外部全文核验闭环端到端

- **现状**：`import_selected_candidates` + `resume_discover_runs_for_paper` 已建，未端到端验证
- **工作**：选 1-2 个真实 OA 外部候选走全链路（选→下载→解析→抽取→全文证据→角色重判）；修暴露 bug；验证 `evidence_level` metadata→fulltext 转换 + 硬门槛计数；接入 ExternalNoveltyAgent
- **验收**：外部候选走完全链路，机会硬门槛（≥2 篇独立全文）能过
- **依赖**：MA

### W2 — 机会生成质量验证

- **现状**：`_synthesize_candidates` 多候选已建，未质量验证
- **工作**：主 Case 跑 1-3 次看多候选区分度；Critic 反馈注入 OpportunityAgent 后质量复查；生成审计（prompt/model/corpus/检索快照记入 run）
- **验收**：2-3 个有区分度候选；Unsupported ≤20%（可暂缓）
- **依赖**：MA, W1

### W4 — 前端：agent 呈现 + 计划页 + Timeline

- **现状**：DiscoverPage 完整（run/外部候选/机会/4 决策/证据回链/转计划）；ResearchPlansPage 占位（18 行）
- **工作**：run 详情展示 agent 交接流（Timeline）；研究计划页（列表/详情/回链）；机会呈现信息密度优化
- **验收**：agent 交接 UI 可见；"编辑确认 → 计划 → 计划页回链"走通
- **依赖**：MA（agent 日志 API）；可与 W1/W2 并行

### W5 — 端到端验收 + 失败降级

- **现状**：代码全有，未系统验证
- **工作**：HITL 4 决策 × API/UI/测试 + Timeline；S2 429 / LLM 失败降级演练；**多智能体场景下某 agent 失败 → Orchestrator 降级继续**
- **验收**：正常 + 降级路径都跑通
- **依赖**：MA, W1, W2, W4

### W6 — 封版 + 演示预演

- **现状**：未开始
- **工作**：冻结版本（语料/标注/Prompt/模型/解析器/Schema）；3 次全新 DB 端到端；记录耗时/错误率/token 成本；演示脚本（含 agent 协同展示）
- **依赖**：W5

### W7 — 全生命周期 agent（Analyze / Write / Respond）

- **现状**：未建
- **工作**：AnalyzeAgent（结果输入 → 对照证伪标准 → 结论+证据引用）；WriteAgent（机会+计划+证据 → 章节草稿）；RespondAgent（审稿意见 → 回复草稿）；轻量数据模型 + 前端入口
- **验收**：主 Case 从确认计划 → 模拟实验结果 → 分析结论 → 论文草稿 → 审稿回复一条链走通
- **依赖**：W4（计划）；可与 W5 并行
- **原则**：结果分析吃手动数据（不自动跑实验）；产物回链证据；轻量不作 Gate

---

## 5. 依赖与优先级

```
MA ──→ W1 ──→ W2 ──→ W5 ──→ W6
  │           │        ↑
  └──→ W4 ────┘        │
  （W4 并行）           │
  MA → W4 → W7 ────────┘
```

**优先级**：MA（架构底座，对齐题目）→ W1（外部闭环）→ W2（质量）→ W4（前端，并行）→ W7（生命周期）→ W5（端到端）→ W6（封版）

---

## 6. 完整度评估

**对比赛 Demo 的 MVP 闭环：足够完整（W1-W7 完成后）**

| 研究生命周期 | 状态 |
|---|---|
| 导入 → 抽取 → 证据回链 | ✅ 已完整 |
| Workspace 检索三合一 | ✅ 可用（质量中等）|
| 外部新颖性核验（metadata + 全文）| ✅ W1 后 |
| 多智能体协同（Planner/Critic 循环）| ✅ MA 后 |
| 多候选机会 + 证据门 + 收窄/否定 | ✅ MA/W2 后 |
| HITL 4 决策 + Timeline | ✅ W4 后 |
| 研究计划 + 回链 | ✅ 已能 |
| 结果分析 / 论文写作 / 审稿回复 | ✅ W7 后（轻量）|
| 降级路径 | ✅ W5 后 |
| 封版演示 | ✅ W6 后 |

**诚实缺口（不假装完整）**：
- 检索质量 Gate 未过（similar 0.778 / counter 0.667）——性能优化已搁置，demo 作 baseline，文档标注"演示级"
- 外部自动生成 recall 0.286——管线已验证、候选主题相关，demo 中作"辅助线索 + 人工选择"
- P1 语义去重 / 抽取模型微调（zf 并行）——质量增强，非 demo 阻塞

**明确不做（暂停范围）**：实验自动执行（Execute）、GNN 排序、多用户认证/协作、重型评估框架。

---

## 7. 验收清单（end-to-end）

- [ ] 导入 → 抽取 → 检索可用
- [ ] Discover Run 以多智能体协同运行（agent 交接 + Critic 循环）
- [ ] 外部全文核验闭环（选→下载→解析→抽取→角色重判）
- [ ] 多候选机会 + 证据不足时系统主动收窄/否定
- [ ] HITL 4 决策 × API/UI/测试 + Timeline 追溯
- [ ] 研究计划 → 结果分析 → 论文草稿 → 审稿回复一条链
- [ ] 正常 + 降级路径都跑通
- [ ] 3 次全新数据库端到端
- [ ] 版本冻结 + 耗时/错误率/token 记录
- [ ] 所有关键结论 UI 回链论文原文

---

## 8. 详细 TODO list

> 每个工作流拆成可执行项。编号即建议执行顺序。状态图例：☐ 未开始 / ⏳ 进行中 / ✅ 完成

### MA 多智能体骨架（架构底座，优先）

| # | TODO | 状态 |
|---|---|---|
| MA-1 | 设计 Agent 抽象契约：role prompt + 可调用 tools（现有 service 方法）+ input/output schema | ☐ |
| MA-2 | 设计 ResearchContext 数据模型：research_question / evidence 账本 / opportunities / gate / agent_log | ☐ |
| MA-3 | 新建 `discover/agents.py`：Agent 基类 + 各 Agent 实现 + ResearchContext + agent_log 写入 | ☐ |
| MA-4 | **Orchestrator 循环**：重构 `execute_run` 为 Planner 驱动（Plan→dispatch→collect→decide）| ☐ |
| MA-5 | EvidenceAgent：包装 `_workspace_similar/_counter/_supporting` | ☐ |
| MA-6 | ExternalNoveltyAgent：包装 `_external_query_plan/_external_verify` + 角色判别 | ☐ |
| MA-7 | OpportunityAgent：包装 `_synthesize_candidates` | ☐ |
| MA-8 | GateAgent：包装 `_evidence_gate` + `needs_more_evidence` 明细 | ☐ |
| MA-9 | **CriticAgent（新）**：对抗性审查机会 → challenges 列表 + 收窄建议 | ☐ |
| MA-10 | Orchestrator 决策逻辑：Critic 有 gap → 收窄（换角度重试）/ 否定（标记弱机会+理由）| ☐ |
| MA-11 | agent_log → Timeline（`discover.agent.*` 事件，含每 agent 输入/输出摘要）| ☐ |
| MA-12 | 迁移/修复现有 265 测试 + 新增 Orchestrator/Critic 单测 | ☐ |
| MA-13 | 主 Case 端到端跑通（agent 交接可见 + Critic 收窄/否定可见）| ☐ |

### W1 外部全文核验闭环端到端

| # | TODO | 状态 |
|---|---|---|
| W1-1 | 从 gold set 选 1-2 个可下载的 OA 外部候选 | ☐ |
| W1-2 | 走通 `import_selected_candidates` 全链路：选→下载→parse task→extract task | ☐ |
| W1-3 | 修下载/解析/抽取失败路径暴露的 bug | ☐ |
| W1-4 | 验证 `evidence_level` metadata_only→full_text 转换 + 硬门槛（≥2 独立全文）计数 | ☐ |
| W1-5 | 全文证据→LLM 角色重判（用全文而非 metadata）| ☐ |
| W1-6 | `resume_discover_runs_for_paper` 触发全文验证的等待→恢复流程 | ☐ |
| W1-7 | 接入 ExternalNoveltyAgent + 单测 | ☐ |
| W1-8 | 验收：机会硬门槛能过 | ☐ |

### W2 机会生成多候选质量验证

| # | TODO | 状态 |
|---|---|---|
| W2-1 | 主 Case 跑 1-3 次 Discover Run，人工检查多候选区分度 | ☐ |
| W2-2 | Critic 反馈注入 OpportunityAgent prompt（challenges 作为约束）| ☐ |
| W2-3 | 生成审计字段：prompt_version / model / corpus / 检索快照记入 run | ☐ |
| W2-4 | Unsupported 主张检查（目标 ≤20%，可暂缓）| ☐ |
| W2-5 | 验收：2-3 个有区分度候选 | ☐ |

### W4 前端 agent 呈现 + 计划页 + Timeline

| # | TODO | 状态 |
|---|---|---|
| W4-1 | run 详情展示 agent 交接流（Timeline / `discover.agent.*` 事件）| ☐ |
| W4-2 | ResearchPlansPage：占位 → 计划列表 + 详情 + 证据回链 | ☐ |
| W4-3 | 机会呈现优化：列表决策信息密度（问题/证据强度/置信度一目了然）| ☐ |
| W4-4 | 验收：agent 交接 UI 可见；"编辑确认→计划→计划页回链"走通 | ☐ |

### W7 全生命周期 agent（Analyze / Write / Respond）

| # | TODO | 状态 |
|---|---|---|
| W7-1 | 轻量数据模型：分析结论 / 论文草稿 / 审稿回复产物（挂 opportunity/plan + 证据引用）| ☐ |
| W7-2 | AnalyzeAgent：输入实验结果 JSON → 对照证伪标准 → 结论 + 证据引用 | ☐ |
| W7-3 | WriteAgent：机会+计划+证据 → 章节草稿（Abstract/Intro/Method/Experiments）| ☐ |
| W7-4 | RespondAgent：论文 + 审稿意见 → 逐条回复草稿 | ☐ |
| W7-5 | 前端入口：plan 详情加"分析结果 / 写作 / 审稿" | ☐ |
| W7-6 | 验收：确认计划→模拟实验→分析→论文草稿→审稿回复一条链 | ☐ |

### W5 端到端验收 + 失败降级

| # | TODO | 状态 |
|---|---|---|
| W5-1 | HITL 4 决策 × API 测试（确认/编辑确认/拒绝/延后）| ☐ |
| W5-2 | 4 决策 × UI 走查 | ☐ |
| W5-3 | Timeline 追溯验证（决策历史可回溯）| ☐ |
| W5-4 | 失败降级演练：S2 429 / LLM 挂 → 系统降级仍可用 | ☐ |
| W5-5 | 多智能体降级：某 agent 失败 → Orchestrator 降级继续 | ☐ |
| W5-6 | 验收：正常 + 降级路径都跑通 | ☐ |

### W6 封版 + 演示预演

| # | TODO | 状态 |
|---|---|---|
| W6-1 | 冻结版本清单：语料 / 标注 / Prompt / 模型 / 解析器 / Schema | ☐ |
| W6-2 | 3 次全新数据库端到端演练 | ☐ |
| W6-3 | 记录解析/抽取/检索/发现的耗时、错误率、token 成本 | ☐ |
| W6-4 | 演示脚本打磨（含多智能体协同展示 + 证据回链）| ☐ |
| W6-5 | 验收：演示可复现 | ☐ |

## 状态更新记录

| 日期 | 内容 |
|---|---|
| 2026-08-06 | 规划稿；多智能体对齐题目 + 全生命周期补全（MA + W1-W7）|

