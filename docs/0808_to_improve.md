# GapMind 总体优化建议

> 日期：2026-08-08
>
> 范围：产品闭环、前端体验、后端逻辑、AI 可信度、系统可靠性与差异化亮点
> 原则：优先解决影响整体价值和完整度的问题，暂缓局部样式、低频功能和过度工程化。

## 1. 总体结论

GapMind 当前的产品方向和基础架构总体合理，不建议推倒重做。项目已经形成了一条有辨识度的主链路：

```text
创建课题空间
→ 搜索或上传论文
→ PDF 解析、分块和向量化
→ 知识抽取与人工审核
→ Workspace RAG、相似工作与反证检索
→ Discover 外部新颖性核验
→ 研究机会候选与人工决策
→ 研究计划与代码产物
```

项目最有价值的部分不是“能搜索论文”或“能和大模型聊天”，而是以下组合：

1. 所有研究活动都以 Workspace 为上下文边界；
2. AI 结论能够回链论文、证据片段和原文位置；
3. Discover 同时考虑支持证据、相似工作、反证和外部新颖性；
4. 研究机会必须经过人工确认才能进入研究计划；
5. 长任务具有持久化状态、历史记录和重试入口。

这套组合已经明显强于普通的“论文搜索 + RAG 对话”产品。当前最需要解决的问题不是继续增加零散页面，而是让这条链路更容易理解、更可靠、更可量化，并把“多智能体协作”和“证据可信度”真正做成用户可感知的核心亮点。

## 2. 当前系统评价

| 维度 | 当前判断 | 主要依据 | 结论 |
|---|---|---|---|
| 产品定位 | 较强 | Evidence-grounded、HITL、外部新颖性核验和 Research Opportunity 组合清晰 | 应继续强化，不要退化为普通聊天工具 |
| 功能闭环 | 基本形成 | 文献、知识、检索、Discover、Plan、Agent 已连通 | 目前闭环主要停在“计划和代码产物”，研究执行与结果分析尚未闭合 |
| 前端功能划分 | 总体合理 | 全局层与 Workspace 层职责清楚，复杂任务有独立 Workbench | Workspace 一级入口略多，状态和下一步仍分散在不同页面 |
| 前端视觉与交互 | 已达到可用水平 | 页面骨架、卡片、抽屉、图谱和处理中心已经统一 | 中英文混用、加载策略和复杂页面信息密度仍影响专业感，但不是首要问题 |
| 后端领域设计 | 方向合理 | Workspace、Paper、Knowledge、Retrieval、Discover、Chat、Agent、Task 分域清楚 | 编排服务过大，运行状态分散在 Task、DiscoverRun、AgentRun，维护和恢复成本开始上升 |
| AI 可信度 | 设计先进、指标未封板 | 有引用、证据等级、Judge、Gate 和人工审核 | 完整 Retrieval Gate 与外部 query 自动生成仍未达目标，不能只靠 UI 展示提升可信度 |
| 异步可靠性 | 有基础、未生产化 | Celery、状态机、重试、取消和审计记录已存在 | 缺少依赖级 readiness、worker 心跳、卡死任务恢复、统一运行观测和成本统计 |
| 工程交付 | 测试基础较好 | 当前后端 284 个测试、前端 20 个测试，OpenAPI 类型自动生成 | 缺少 CI、端到端测试和包含应用服务的统一部署方案 |
| 部署与多用户 | 适合本地单用户 | Docker Compose 已覆盖 PostgreSQL、Redis、Milvus | FastAPI、Worker、Frontend 未容器化；`X-User-ID` 不是认证；本地 Artifact/JSONL 不适合多实例 |

## 3. 当前设计中应当保留的部分

### 3.1 全局层与 Workspace 层的划分

全局首页、论文检索、课题空间和全局 AI 助手负责“选择研究上下文”；Workspace 内的文献、知识、发现、研究计划和 AI 助手负责“围绕具体课题推进研究”。这个结构是合理的。全局 AI 助手不应重新变成无上下文的核心入口，而应继续承担课题选择、会话发现和进入 Workspace 的导航作用。

### 3.2 模块化单体后端

现阶段继续使用 FastAPI 模块化单体是正确选择。项目规模尚不需要微服务；拆成微服务会引入部署、事务和链路追踪成本。优化重点应是缩小大型 Service、明确跨域接口和统一运行协议，而不是更换技术栈。

### 3.3 单一 Milvus Collection 加 Workspace 过滤

当前用统一 Collection 存储论文 chunk，并以 `workspace_id` 过滤隔离，是比“每个 Workspace 建一个 Collection”更合理的方案。它便于索引维护、升级和跨版本管理。应继续强化隔离测试和过滤下推，不需要改成大量独立向量库。

### 3.4 Human-in-the-Loop 与不可变版本

Opportunity Version、HumanDecision、Evidence Gate 和确认后再生成 ResearchPlan，是当前最有价值的设计之一。后续任何 Agent 都应继续遵守“AI 只提出候选，关键资产由用户确认”的原则。

### 3.5 长任务异步化

PDF 解析、知识抽取、向量化、Discover 和 Agent 使用 Celery 是合理的。问题不在于是否异步，而在于运行状态、失败恢复和用户反馈还需要统一。

## 4. 最高优先级优化建议

以下四项建议优先完成。它们决定项目是否从“功能丰富的 Demo”升级为“完整、可信、可演示的科研辅助系统”。

### P0-1：建立统一的“研究准备度与下一步”模型

#### 当前问题

系统已经有大量能力，但用户仍需要自己判断：论文是否解析完成、向量是否可用、知识是否需要审核、Discover 是否具备启动条件、Opportunity 为什么不能确认、计划是否已经能用于代码生成。现有概览页会推荐下一步，但判断依据分散在前端多个请求和局部状态中，不是稳定的领域能力。

#### 推荐方案

新增后端 `WorkspaceReadinessService`，统一输出以下状态：

- `corpus_ready`：有多少论文、PDF、已解析论文；
- `retrieval_ready`：索引数量、最后一次索引时间、向量服务状态；
- `knowledge_ready`：知识条目数量、待审核数量、证据回链覆盖率；
- `discover_ready`：是否满足 Discover 最小条件、缺失项和可降级项；
- `research_ready`：已确认 Opportunity、ResearchPlan 和可供 Agent 使用的计划；
- `blocking_actions` 与 `recommended_next_action`。

建议提供一个聚合接口，例如：

```text
GET /api/v1/workspaces/{workspace_id}/summary
GET /api/v1/workspaces/{workspace_id}/readiness
```

前端在 Workspace 顶部持续展示一个紧凑的研究进度条：

```text
文献准备 → 知识审核 → 机会发现 → 人工确认 → 研究计划 → 研究执行
```

每个阶段只展示一个最重要的下一步，不把所有异常同时抛给用户。首页、Workspace 概览、处理中心和 Discover 共享同一套后端结果，避免各自计算出不同数量或状态。

#### 验收标准

- 同一个 Workspace 在首页、概览、Discover 和研究中心显示的数量完全一致；
- 任意阻塞状态都能解释“为什么不能继续”和“应该去哪处理”；
- 页面刷新和路由切换不会丢失当前进度；
- 概览页不再为每个 Workspace 发起 5 个以上独立请求。

### P0-2：把证据可信度做成统一的 Evidence Passport

#### 当前问题

项目已经保存 EvidenceSpan、ChatMessageEvidence、OpportunityEvidence 和 Agent 上下文，但这些证据分别属于不同模块。用户看到置信度时，很难快速区分：模型自信、检索相关度、证据覆盖率、全文核验状态和人工确认状态。当前完整 Retrieval Gate 中 Similar Work Recall@10 为 0.778、Counter Evidence Recall@10 为 0.667；外部 query 自动生成 Recall@10 为 0.286。这说明系统链路可用，但质量仍需继续提升，不能把“有引用”直接等同于“结论可靠”。

#### 推荐方案

建立统一的 `EvidenceManifest`（可以先作为 API schema 和 JSON 快照，不必立即新增复杂表），供 Chat、Opportunity、ResearchPlan 和 AgentArtifact 复用：

- 支持、限定、反驳、相似工作的证据数量；
- 独立论文数量与全文证据数量；
- metadata-only 与 full-text 的明确区分；
- 每条关键结论引用了哪些 Evidence；
- 证据覆盖率、冲突状态、外部核验状态；
- Prompt、模型、Embedding、Reranker、Corpus 和 Artifact 版本；
- 人工审核状态。

前端不要只显示一个百分比，而应显示“可信度卡片”：

```text
证据覆盖：4/5 个关键结论
全文来源：3 篇独立论文
反证状态：发现 2 条限定证据
外部核验：已完成
人工状态：待确认
```

同时增加自动一致性检查：LLM 输出中的 `[E1]` 等引用必须真实存在；关键结论没有引用时标记为 unsupported；引用原文与当前 Artifact 版本不一致时标记为 stale。评测应保留一套固定核心 Gold Set，再增加一套“产品相关性评测”，不要为了让指标过线而直接调整固定 Gold Set。

#### 验收标准

- Chat、Opportunity、Plan 和 Agent 产物使用同一套证据状态语义；
- 所有关键结论可一键回到原文并高亮；
- 不存在的引用、过期引用和 metadata-only 关键结论会被自动拦截或警告；
- 完整 Retrieval Gate 达到既定阈值后再宣称质量封板；
- 每次模型、Prompt、Embedding 或 Corpus 变更都能重跑固定评测并比较结果。

### P0-3：把 Discover 升级为真正可感知的有界多智能体协作

#### 当前问题

当前 `DiscoverService` 仍承担大型单体编排，`backend/app/domains/discover/service.py` 已接近 1800 行。现有通用 Agent 系统支持 `research_plan` 和 `code_generation` 两种任务，但它们是两个独立的受控工作流，并不等同于多个 Agent 围绕同一研究问题协作。如果项目对外强调“多智能体科研辅助”，目前的实现和展示仍不够有说服力。

#### 推荐方案

不要引入重量级 Agent 框架，直接复用现有 Service、`AgentRun`、`AgentStep`、Task 和 Timeline，建立有界角色：

1. `PlannerAgent`：分解研究问题并生成检索计划；
2. `EvidenceAgent`：执行 Workspace semantic/similar/counter 检索；
3. `ExternalNoveltyAgent`：生成外部检索轴、调用 Semantic Scholar、管理全文核验；
4. `CriticAgent`：挑战候选机会，指出证据缺口和已有工作重叠；
5. `OpportunityAgent`：综合多个候选；
6. `GateAgent`：执行确定性证据门槛，决定可确认、需补证或否定；
7. `PlanAgent`：仅处理已确认的 Opportunity 或用户明确发起的计划任务。

Orchestrator 只允许有限次数的“补证据或收窄”循环，并持久化每一步的结构化输入、输出摘要和状态。前端展示的是 Agent 交接、调用了哪些工具、获得了多少证据和为什么进入下一阶段，不展示模型隐藏推理过程。

这项优化同时应拆分 `DiscoverService`：运行生命周期、外部检索、证据装配、候选综合、Gate 和持久化分别成为可测试服务，Orchestrator 只负责状态推进。

#### 验收标准

- 用户能看到 Planner → Evidence/External → Critic → Synthesis → Gate 的交接过程；
- 任一 Agent 失败时有明确降级策略，不会把整个 Run 永久留在 running；
- Critic 至少能够触发一次“补证据、收窄或否定”，而不是永远通过；
- 相同输入、版本和外部快照可以复现最终 Opportunity；
- 每个 Agent 有独立单元测试，完整流程有固定案例端到端测试。

### P0-4：补齐异步任务的可靠性与可观测性

#### 当前问题

系统已经有 Task 状态机、取消、重试和 Timeline，但 `/health/ready` 目前只检查 LLM 与 Embedding Key 是否存在，没有真实检查 PostgreSQL、Redis、Milvus、Celery worker 和 Artifact 存储。Task、DiscoverRun 和 AgentRun 也有各自状态，Worker 异常退出后可能出现数据库显示 running、实际没有任务执行的情况。当前日志是结构化的，但缺少统一 request/run/task 关联、耗时、失败率和 token 成本视图。

#### 推荐方案

- 将 health 拆为 liveness、readiness 和 capability：真实检查 DB、Redis、Milvus、Artifact 目录，读取 Celery worker heartbeat；外部 API 只做配置状态和最近调用状态，不在每次 readiness 中产生昂贵请求；
- 为 Task、DiscoverRun、AgentRun 建立统一的运行协议：共同状态语义、`correlation_id`、最后心跳、当前 step、可重试性和取消语义；
- 增加任务 lease 与 reconciliation：超过阈值未更新的 running 任务自动标记为 interrupted，并允许安全重试；
- 所有 spawn 操作增加 idempotency key，防止重复点击产生重复解析、重复 Agent 或重复 Opportunity；
- 记录外部调用的 provider、model、latency、token、重试次数、429/5xx 和降级结果；
- 处理中心以业务任务为主线合并展示 Task、Discover 和 Agent，不要求用户理解三套内部对象。

#### 验收标准

- Redis、Milvus、Worker 或外部模型不可用时，用户能在开始任务前看到具体能力状态；
- Worker 被强制关闭后，任务能够被识别为 interrupted，并可恢复或安全重试；
- 重复点击不会生成重复业务资产；
- 可以按一次 Run 查看完整耗时、步骤、模型调用、token 和失败原因；
- 完成 Semantic Scholar 429、LLM 超时、Milvus 不可用和 PDF 下载失败四类降级演练。

## 5. 第二优先级优化建议

### P1-1：把研究中心从“计划列表”升级为“研究执行中心”

当前研究中心已经能收纳已确认 Opportunity 和 ResearchPlan，但“深度研究”仍是占位，代码产物也主要停留在对话消息中。下一步最有价值的新增功能不是论文写作，而是完成一个最小研究执行闭环：

```text
确认 Opportunity
→ 生成并编辑 ResearchPlan
→ 拆分里程碑与实验任务
→ 生成代码方案或实验配置
→ 用户上传实验结果
→ AnalyzeAgent 对照指标与证伪标准分析
→ 形成带证据的 Research Memo
```

建议增加 Plan Version、Milestone/Experiment、ResultArtifact 和 AnalysisReport。代码只生成、预览、下载和可选语法验证，不自动执行未知项目。这样既保持安全边界，也让“计划 → 实验 → 结论”成为可演示的完整研究生命周期。

验收重点：计划可编辑且保留版本；每个实验任务关联数据集、基线、指标和证伪条件；上传结果后明确输出“支持、部分支持或否定假设”；结论回链计划、结果文件和论文证据。

### P1-2：简化 Workspace 信息架构并建立统一前端数据层

当前全局导航合理，Workspace 的八个一级入口略多。建议保留六个主要入口：

```text
概览 | 文献 | 知识 | 发现 | 研究 | AI 助手
```

“动态”合并到顶部处理中心，“设置”放在 Workspace 标题区或更多菜单。知识审核和知识图谱继续作为“知识”的二级视图；Opportunity、ResearchPlan、Agent 运行和后续实验统一归入“研究”。这样不会删除功能，只会让用户更容易理解功能阶段。

数据加载方面，当前页面大量使用独立 `useEffect`、`Promise.allSettled` 和轮询：首页会针对每个 Workspace 请求论文、任务、知识、Run 和 Opportunity，Workspace 概览也会再次请求多个列表。这会造成首屏慢、重复请求和不同页面状态短暂不一致。建议：

- 用后端 summary/readiness 聚合接口替代前端统计；
- 引入统一 Query Cache（可使用 TanStack Query，也可以先实现轻量 API cache），统一 stale time、重试、取消、预取和轮询；
- 路由切换时保留上一份成功数据，使用局部 skeleton，不清空整个页面；
- 对活跃 Task/Run 使用自适应轮询，完成后自动停止；后续再考虑 SSE；
- 把 KnowledgeGraph、SemanticPaperSearch、KnowledgeWorkbench 等大型组件继续按数据、画布和详情面板拆分。

验收重点：Workspace 主页面二次进入可立即展示缓存；首页请求数量与 Workspace 数量不再线性增长；切换知识工作台和图谱时布局不跳动；状态标签、按钮和错误信息统一使用中文产品语言。

### P1-3：建立可协作、可部署的工程基线

当前仓库没有 CI，Docker Compose 只覆盖基础设施。为了让协作者拉取后能够稳定运行，建议补齐：

- GitHub Actions：后端测试、Ruff、前端测试、typecheck、build、OpenAPI 生成差异、Alembic 单 head 和离线迁移检查；
- 增加 backend、worker、frontend 的 Dockerfile，并提供 `local-infra` 与 `full-app` 两种 Compose profile；
- 启动脚本在运行前检查迁移状态、环境变量、Redis、Milvus 和 Worker；
- ArtifactStore 抽象：数据库中的 Artifact 是唯一入口，chunk 不再依赖代码目录下固定 JSONL 路径；本地开发使用文件系统，部署时可切换对象存储；
- 增加数据库与 Artifact 备份/恢复说明；
- 如果部署到多人可访问环境，再引入真实认证和 workspace ownership。当前 `X-User-ID` 只适合单用户开发，不能作为安全边界。

验收重点：新环境按一份文档可启动；每个 PR 自动验证；全新数据库可以连续完成三次核心流程；多实例部署不会因为本地文件路径导致证据或 chunk 丢失。

## 6. 最值得强化的三个产品亮点

### 6.1 “为什么这是研究机会”证据面板

不要只展示 Opportunity 文本。把支持证据、最相似已有工作、反证/限定证据和仍缺失的证据放在同一个对比视图中，让用户一眼看到“已有工作做了什么、还缺什么、为什么值得研究”。这会比单纯知识图谱更直接地体现 GapMind 的价值。

### 6.2 可回放的多智能体研究过程

用结构化 Timeline 展示每个 Agent 接收了什么任务、调用了什么能力、产出了什么可审计结果、Critic 提出了什么挑战、Gate 为什么通过或拒绝。重点是“协作和证据”，不是展示大段模型思考文本。这是最适合比赛演示和产品宣传的亮点。

### 6.3 Research Gap Map

在现有知识图谱之外增加更面向科研决策的矩阵视图，例如“方法 × 任务/数据集/设置/评测指标”。有证据的组合显示论文和结论，证据冲突的组合显示警告，明显缺失且有相邻证据支持的组合成为 Discover 输入。这样知识图谱不再只是关系浏览器，而是能够直接产生研究问题的工具。

## 7. 推荐实施顺序

### Milestone 1：可信闭环封板

1. 建立 Workspace summary/readiness；
2. 统一 EvidenceManifest 和可信度展示；
3. 修到完整 Retrieval Gate 达标，并固定评测版本；
4. 完成核心流程端到端测试：导入并处理论文、Workspace RAG 引用、Discover 到确认和 Plan；
5. 完成 429、LLM 超时、Milvus 不可用和 Worker 中断演练。

这一阶段完成前，不建议继续增加更多 Agent 类型。

### Milestone 2：多智能体与亮点强化

1. 拆分 Discover 大型编排服务；
2. 落地 Planner、Evidence、ExternalNovelty、Critic、Opportunity 和 Gate 的有界协作；
3. 增加 Agent 交接 UI 和“为什么这是机会”的证据面板；
4. 让 Opportunity、Plan、Chat 和 AgentArtifact 共用 Evidence Passport。

### Milestone 3：研究执行闭环

1. ResearchPlan 编辑与版本；
2. Milestone/Experiment 与 ResultArtifact；
3. Code Agent 绑定实验任务；
4. AnalyzeAgent 对照证伪标准生成 Research Memo；
5. Research Gap Map 作为 Discover 的新入口。

### Milestone 4：工程与部署完善

1. CI、应用容器化和全新环境验收；
2. 统一前端 Query Cache 与性能优化；
3. ArtifactStore 抽象和备份恢复；
4. 确认需要远程部署或多人协作后，再实现认证与权限。

## 8. 暂时不推荐优先做的事情

- 不要为了“多智能体”数量继续增加没有独立状态、工具和验收标准的 Agent；
- 不要自动执行 Agent 生成的完整代码项目，继续保持默认只预览和下载；
- 不要先做论文全文自动写作、自动投稿或审稿回复，这些能力依赖尚未闭合的实验结果链路；
- 不要拆微服务或为每个 Workspace 建独立 Milvus Collection；
- 不要先投入大量时间重做颜色、圆角、动画和局部间距；
- 不要在产品目标未确定为多人在线服务前投入完整组织、角色和权限系统；
- 不要依赖增加模型调用次数来掩盖 Retrieval 和 Evidence 质量问题；
- 不要为了通过评测随意改 Gold Set，应区分固定基准与产品相关性评测。

## 9. 最终建议

GapMind 下一阶段最正确的方向是“收敛并做深”，而不是“继续横向加功能”。优先把研究准备度、证据可信度、Discover 多智能体协作和异步可靠性做成统一体系；随后用研究执行中心把计划、代码、实验结果和分析串起来。完成这些内容后，GapMind 的核心卖点可以清晰表述为：

> GapMind 不是替用户生成一个听起来合理的研究答案，而是让多个受控 Agent 在可追溯证据上提出、质疑、验证并推进研究机会，最终由用户确认并沉淀为可执行、可证伪的研究计划。

这比继续增加搜索筛选、普通聊天模式或局部界面美化，更能提升整体系统价值、用户体验和项目辨识度。
