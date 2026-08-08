# ZWX 近期工作交接说明（2026-08-07 ～ 2026-08-08）

> 作者：Zhuwen Xuan（zwx）
>
> 交接对象：GapMind 项目协作者
>
> 分支：`zwx`
>
> 对比基线：`origin/main`（`4ccf790`）
>
> 当前提交：`9f26ed3`
>
> Pull Request：[PR #15 - feat: 完善工作区研究闭环与多智能体助手](https://github.com/yuanxing629/GapMind/pull/15)
>
> 统计：6 个提交、74 个文件、7361 行新增、1019 行删除

## 1. 工作目标与总体结果

本轮工作的核心目标不是继续增加相互独立的页面，而是把 GapMind 已有的文献、知识、检索、Discover 和对话能力串成一条以 Workspace 为边界的研究闭环。完成后的主要流程如下：

```text
工作区论文与知识
→ Workspace RAG 对话与证据定位
→ Discover 发现与外部候选处理
→ Opportunity 人工确认
→ 研究中心统一收纳
→ Research Plan Agent 生成研究计划草案
→ 人工确认计划
→ Code Generation Agent 生成代码项目
→ 预览、下载与可选的隔离语法验证
```

本轮同时优化了知识审核和知识图谱的展示方式，修复了 Discover 历史记录、外部候选选择和阶段状态表达中的问题。

需要特别说明：代码中的 Agent 模块已经建立统一的 `AgentRun → AgentStep → AgentArtifact` 运行协议，并实现“研究计划生成”和“代码生成”两类受控 Agent；它们目前是两个可选择、可追踪的工作流，还不是多个角色自主协商和互相调用的完整多智能体编排。

## 2. 提交范围

本次 PR 包含以下 6 个提交，存在前后依赖，建议整体合并；如果必须 cherry-pick，应严格按下表顺序执行。

| 顺序 | Commit | 主题 | 核心内容 |
|---|---|---|---|
| 1 | `0ed2bc4` | `fix` | Discover Run 软删除、阶段状态和候选统计修复 |
| 2 | `902d4ca` | `workspace ai agent` | Workspace RAG 对话、证据持久化与知识图谱深度优化 |
| 3 | `0dd2b4a` | `知识展示优化` | 知识工作台单/双列视图、全局 AI 助手入口和布局优化 |
| 4 | `6880c6b` | `fix discover pipline` | Discover 外部候选为空时的状态修复与跳过选择逻辑 |
| 5 | `879bc12` | `新增研究中心` | Opportunity Portfolio、研究计划列表和转换流程 |
| 6 | `9f26ed3` | `multi agent` | Agent 数据模型、异步任务、研究计划/代码生成、产物下载和安全验证 |

`docs/0808_to_improve.md` 是本地后续优化分析，目前未提交、未推送，也不属于 PR #15。

## 3. 详细实现内容

### 3.1 Discover 流程管理与状态修复

#### 已实现功能

- Discover 历史运行支持软删除，删除后不会继续出现在正常历史列表和概览统计中。
- 新增 `deleted_at`、`deleted_by` 字段，保留审计信息，不直接物理删除运行及关联结果。
- 外部搜索完成后，用户可以选择候选论文，也可以点击跳过，仅使用工作区已有知识继续生成 Opportunity。
- 外部搜索没有返回候选时，不再把该阶段错误地显示为成功；前端会表达未发现外部候选的实际结果。
- 修复阶段状态、当前阶段、候选数量和概览待处理机会数不同步的问题。
- 已删除 Discover Run 产生的 Opportunity 不计入正常待处理统计。
- Opportunity 的确认、编辑确认、拒绝、延后和转换研究计划流程继续保留。

#### 主要接口

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/api/v1/workspaces/{workspace_id}/discover/runs` | 获取未删除的 Discover 历史运行 |
| `DELETE` | `/api/v1/workspaces/{workspace_id}/discover/runs/{run_id}` | 软删除指定运行 |
| `POST` | `/api/v1/workspaces/{workspace_id}/discover/runs/{run_id}/external-selection` | 提交外部论文选择 |
| `POST` | `/api/v1/workspaces/{workspace_id}/discover/runs/{run_id}/external-selection/skip` | 跳过外部选择并继续流程 |
| `GET` | `/api/v1/workspaces/{workspace_id}/discover/opportunities` | 查询 Opportunity 候选 |
| `POST` | `/api/v1/workspaces/{workspace_id}/discover/opportunities/{opportunity_id}/confirm` | 确认 Opportunity |
| `POST` | `/api/v1/workspaces/{workspace_id}/discover/opportunities/{opportunity_id}/convert` | 转换为研究计划 |

#### 协作者注意事项

- `discover_create_run_422` 已统一为 `discover_input_invalid`，如果前端或测试硬编码旧错误码，需要同步修改。
- `_call_llm_with_retry` 已改名为 `call_llm_with_retry`；对该函数做 monkeypatch 的测试需要使用新路径。
- 删除是软删除，排查数据时应检查 `discover_runs.deleted_at`，不能只根据记录是否存在判断。

### 3.2 Workspace RAG 对话

#### 设计思路

全局 AI 助手负责选择研究上下文和进入工作区；真正使用论文知识回答的对话放在 Workspace 内。Conversation 增加 `workspace_id` 后，检索、消息和引用都按工作区隔离，避免跨课题误用证据。

#### 已实现功能

- Conversation 可绑定 `workspace_id`，会话列表支持按工作区过滤。
- 工作区对话调用现有语义检索和 reranker 获取已解析、已向量化论文的相关分块。
- LLM 回答携带持久化 Evidence 引用，而不是只在当前请求中临时拼接文本。
- 引用包含论文、章节、摘录、字符偏移、相关性分数和排序。
- 用户可以从回答引用打开原文上下文，并按 `start_char`、`end_char` 定位证据。
- 若工作区没有可用解析/向量数据，后端返回明确的 grounding 状态，不让 DeepSeek脱离工作区证据直接回答。
- 保留全局普通对话兼容性：`workspace_id` 为空时仍可使用原有全局 Chat。

#### 数据结构变化

- `chat_conversations.workspace_id`：会话所属工作区，可为空以兼容全局对话。
- `chat_messages.grounding_status`：记录是否请求并成功使用工作区证据。
- `chat_message_evidence`：持久化每条助手消息引用的证据及原文偏移。

#### 主要接口变化

| 方法 | 路径 | 变化 |
|---|---|---|
| `GET` | `/api/v1/chat/conversations?workspace_id=...` | 支持按 Workspace 筛选会话 |
| `POST` | `/api/v1/chat/conversations` | 请求体可带 `workspace_id` |
| `POST` | `/api/v1/chat/conversations/send` | 新建会话并发送时可带 `workspace_id` |
| `POST` | `/api/v1/chat/conversations/{conversation_id}/messages` | 在绑定工作区的会话中发送消息 |
| `GET` | `/api/v1/chat/conversations/{conversation_id}/messages/{message_id}/evidence/{evidence_id}/context` | 获取完整原文和定位信息 |

#### 关键配置

```ini
CHAT_RAG_TOP_K=6
CHAT_RAG_MAX_CONTEXT_CHARS=18000
```

### 3.3 AI 助手信息架构与页面体验

- 新增全局 `ChatHubPage`。用户在全局 AI 助手选择 Workspace 后，进入对应课题空间的 AI 助手，而不是在两个位置维护重复的 RAG 页面。
- Workspace 导航新增“AI 助手”入口，保留会话历史、搜索、重命名、删除和失败重试。
- 优化空状态、标题区、输入区和页面宽高，使工作区对话在大屏上能充分利用空间。
- 对话输入区支持三种模式：`资料问答`、`生成研究计划`、`代码生成`。
- Agent 运行通过消息卡片展示状态、阶段、进度、结果和可执行操作。

### 3.4 知识工作台优化

- 重新组织 Knowledge Item 的类型、名称、内容、来源、置信度和审核操作，避免所有内容被压缩在同一行。
- 文本支持合理换行和摘要展示，减少遮挡与横向溢出。
- 右上角增加单列/双列切换，适配“详细审核”和“快速浏览”两类使用场景。
- 保留搜索、类型、状态、来源论文和最低置信度筛选。
- 页面布局宽度与 Workspace 其他页面保持连续，减少切换到知识页或图谱页时突然缩放、位移的问题。

### 3.5 知识图谱可视化优化

#### 前端能力

- 重构图谱布局，减少节点集中成圆环或大范围重叠的情况。
- 节点默认显示可识别标签，支持按节点类型区分颜色和视觉层级。
- 修复节点/关系悬停时 Tooltip 频繁显示、消失和抖动的问题。
- 支持搜索并定位论文、观点、方法、任务和数据集节点。
- 支持单击查看节点详情、双击展开邻居、继续懒加载节点。
- 支持类型、审核状态、来源论文、关系类型、最低置信度等筛选。
- 将复杂图计算拆到 `knowledgeGraph/graphUtils.ts`，并补充工具函数测试。

#### 后端能力

- 扩展知识图谱查询，支持可定位搜索和邻居展开。
- 对图谱数据进行分页和按需加载，避免一次性加载完整知识图。
- 保留 Paper、CanonicalEntity、PaperMention 等知识层次的表达和证据回链能力。

### 3.6 研究中心

研究中心用于收纳 Discover 后真正有后续价值的结果，避免已确认 Opportunity 继续散落在历史运行中。

#### 已实现功能

- Portfolio 视图统一展示已确认、可继续推进的 Opportunity。
- Research Plans 视图统一展示由 Opportunity 转换或 Agent 生成的研究计划。
- 确认后的 Opportunity 可转换为 Research Plan。
- Research Plan 允许两种来源：`opportunity` 和 `agent`。
- 工作区导航中的“研究计划”调整为更完整的“研究”入口。

#### 主要接口

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/api/v1/workspaces/{workspace_id}/discover/portfolio/opportunities` | 获取已确认机会 Portfolio |
| `GET` | `/api/v1/workspaces/{workspace_id}/discover/plans` | 获取研究计划列表 |
| `POST` | `/api/v1/workspaces/{workspace_id}/discover/opportunities/{opportunity_id}/convert` | 将机会转换为研究计划 |

### 3.7 Workspace Agent 运行框架

#### 数据模型

| 模型 | 职责 |
|---|---|
| `AgentRun` | 一次 Agent 任务的总体状态、输入、上下文快照、进度和结果 |
| `AgentStep` | 记录检索、生成、静态检查、等待确认等阶段，便于前端解释过程 |
| `AgentArtifact` | 保存研究计划 Markdown 或生成代码文件，支持预览和下载 |

Agent 与已有 `Task`、Conversation、ChatMessage 和 ResearchPlan 关联。运行状态持久化到 PostgreSQL，实际执行由 Celery worker 完成，刷新页面后仍可恢复查看。

#### Research Plan Agent

1. 根据用户问题检索当前 Workspace 的证据；
2. 可选读取已确认 Opportunity 作为额外上下文；
3. 调用 DeepSeek 生成结构化、可证伪的研究计划；
4. 生成 `research_plan.md` 产物；
5. 进入 `waiting_for_user` 状态；
6. 用户确认后才写入正式 `research_plans` 表。

计划包含研究问题、假设、实验步骤、数据集、评价指标、风险以及 Evidence 引用。人工确认是强制 Gate，Agent 不会直接替用户创建正式研究资产。

#### Code Generation Agent

1. 必须选择当前 Workspace 中已存在的 Research Plan；
2. 重新检索相关工作区证据；
3. 调用 DeepSeek 生成多文件代码项目；
4. 检查文件路径、文件数量和总字符数；
5. 将每个文件保存为 `AgentArtifact`；
6. 支持单文件下载和 ZIP 打包下载。

生成代码默认只预览和下载，不自动执行。

#### 主要接口

所有 Agent API 前缀为 `/api/v1/workspaces/{workspace_id}/agent-runs`。

| 方法 | 相对路径 | 作用 |
|---|---|---|
| `POST` | `（根路径）` | 创建 Agent Run，返回 `202` |
| `GET` | `（根路径）` | 按 Workspace 或 Conversation 查询运行列表 |
| `GET` | `/{run_id}` | 获取运行、步骤和产物详情 |
| `POST` | `/{run_id}/cancel` | 取消排队中或运行中的任务 |
| `POST` | `/{run_id}/confirm` | 确认研究计划草案并创建 Research Plan |
| `POST` | `/{run_id}/validate` | 启动可选的代码语法验证 |
| `GET` | `/{run_id}/artifacts/{artifact_id}` | 下载单个产物 |
| `GET` | `/{run_id}/bundle` | 下载代码 ZIP 包 |

创建研究计划 Agent 的示例请求：

```json
{
  "agent_type": "research_plan",
  "prompt": "基于当前证据生成一个可证伪的研究计划",
  "conversation_id": "<conversation_id>",
  "input": {
    "opportunity_id": "<optional_opportunity_id>"
  }
}
```

创建代码生成 Agent 的示例请求：

```json
{
  "agent_type": "code_generation",
  "prompt": "为这个研究计划生成最小可运行的实验项目",
  "conversation_id": "<conversation_id>",
  "input": {
    "research_plan_id": "<research_plan_id>"
  }
}
```

### 3.8 可选代码验证与安全边界

`AGENT_CODE_EXECUTION_ENABLED` 默认是 `false`，协作者不需要为了使用研究计划生成、代码生成、预览和下载而开启它。只有需要调用 `/{run_id}/validate` 进行 Docker 内 Python 语法验证时才需要手动开启。

验证容器采用以下限制：

- 禁用网络；
- 只读挂载生成文件；
- 限制内存、CPU 和进程数；
- 不自动拉取镜像；
- 只做受控语法检查，不自动运行生成的研究项目。

启用方式：

```ini
AGENT_CODE_EXECUTION_ENABLED=true
AGENT_SANDBOX_IMAGE=python:3.11-slim
```

首次使用前由开发者主动准备镜像：

```powershell
docker pull python:3.11-slim
```

## 4. 数据库迁移

本轮新增三个连续迁移，必须按 Alembic 链执行：

| Migration | 作用 |
|---|---|
| `0012_discover_run_soft_delete` | Discover Run 软删除字段和索引 |
| `0013_workspace_grounded_chat` | Workspace Conversation、消息 grounding 状态和引用证据表 |
| `0014_workspace_agents` | Agent Run/Step/Artifact、Research Plan 的 Agent 来源支持 |

协作者拉取代码后，在 `backend` 目录执行：

```powershell
.venv\Scripts\activate
alembic upgrade head
```

迁移前建议确认当前版本：

```powershell
alembic current
alembic heads
```

不要只更新前端而跳过迁移，否则 Chat、Discover 删除、Agent 和 Research Plan 接口会因为缺表或缺列失败。

## 5. 环境、依赖与启动

### 5.1 是否新增第三方库

- 本轮没有新增前端 npm 依赖，`frontend/package.json` 仅优化了 Windows 下的 OpenAPI 类型生成脚本。
- 本轮没有新增必须单独安装的后端 Python 依赖。
- 使用仓库统一的 `backend/.venv` 即可，不依赖 zwx 个人此前使用过的 Conda 环境。
- Docker 语法验证是可选能力，不开启时无需额外镜像。

### 5.2 新增或重点配置

```ini
# Workspace RAG
CHAT_RAG_TOP_K=6
CHAT_RAG_MAX_CONTEXT_CHARS=18000

# Workspace Agents
AGENT_RAG_TOP_K=10
AGENT_CODE_MAX_FILES=30
AGENT_CODE_MAX_CHARS=300000
AGENT_CODE_EXECUTION_ENABLED=false
AGENT_DOCKER_BINARY=docker
AGENT_SANDBOX_IMAGE=python:3.11-slim
AGENT_SANDBOX_TIMEOUT_SECONDS=60
AGENT_SANDBOX_MEMORY=512m
AGENT_SANDBOX_CPUS=1.0
AGENT_SANDBOX_PIDS=128
```

已有 `.env` 不补这些值时，多数配置会使用代码默认值；但建议协作者与 `backend/.env.example` 对齐，避免不同环境行为不一致。

### 5.3 推荐启动顺序

```powershell
# 1. 项目根目录或 infra 目录启动基础设施
docker compose -f infra\docker-compose.yml up -d

# 2. 更新数据库并启动后端
cd backend
.venv\Scripts\activate
alembic upgrade head
uvicorn app.main:app --reload

# 3. 新终端启动 Celery
cd backend
.venv\Scripts\activate
celery -A app.workers.celery_app worker --loglevel=info

# 4. 新终端启动前端
cd frontend
npm install
npm run gen:api
npm run dev
```

`npm run gen:api` 只负责从 FastAPI OpenAPI 定义重新生成 TypeScript 类型，不能替代 `npm run dev`；接口发生变化后先执行前者，开发时再执行后者。

## 6. 测试与验证结果

PR #15 创建前已完成以下验证：

| 验证项 | 命令 | 结果 |
|---|---|---|
| 后端全量测试 | `backend/.venv/Scripts/python.exe -m pytest -q` | `284 passed` |
| 前端单元测试 | `npm test -- --run` | 6 个测试文件，`20 passed` |
| TypeScript 检查 | `npm run typecheck` | 通过 |
| 前端生产构建 | `npm run build` | 成功，转换 3373 个模块 |
| Git 差异检查 | `git diff --check` | 通过 |

新增或重点覆盖的测试包括：

- Workspace Chat 跨工作区隔离、无向量内容提示、引用持久化和原文上下文读取；
- Discover Run 软删除、跳过外部选择、候选为空、状态转换和统计同步；
- Research Opportunity Portfolio 和研究计划转换；
- Agent API 生命周期、人工确认、产物下载和错误边界；
- Docker Sandbox 配置与安全参数；
- Knowledge Graph 工具函数与前端导航状态。

## 7. 协作者重点 Review 文件

### 后端

- `backend/app/domains/chat/service.py`：Workspace RAG、引用写入和 grounded 回答主逻辑；
- `backend/app/domains/agent/service.py`：两类 Agent 的编排、状态机、证据检索和产物生成；
- `backend/app/domains/agent/router.py`：Agent HTTP 接口；
- `backend/app/domains/agent/sandbox.py`：Docker 验证安全边界；
- `backend/app/domains/discover/opportunity_workflow.py`：Opportunity 决策和研究计划转换；
- `backend/app/domains/discover/service.py`：Discover 阶段和外部选择流程；
- `backend/app/domains/knowledge/service.py`：图谱搜索、邻居和按需查询；
- `backend/alembic/versions/0012_*` ～ `0014_*`：数据库迁移链。

### 前端

- `frontend/src/pages/ChatPage.tsx`：Workspace 对话和 Agent 模式入口；
- `frontend/src/pages/ChatHubPage.tsx`：全局 AI 助手的 Workspace 导航；
- `frontend/src/components/chat/ChatCitations.tsx`：Evidence 引用和原文定位；
- `frontend/src/components/chat/ChatAgentRunCard.tsx`：Agent 运行状态和操作；
- `frontend/src/pages/DiscoverPage.tsx`：Discover 跳过选择、阶段状态和机会处理；
- `frontend/src/pages/ResearchPlansPage.tsx`：Portfolio 和 Research Plans；
- `frontend/src/components/KnowledgeWorkbench.tsx`：单/双列知识审核；
- `frontend/src/components/KnowledgeGraph.tsx`：图谱交互主组件；
- `frontend/src/components/knowledgeGraph/graphUtils.ts`：图谱数据转换与布局辅助。

## 8. 已知风险与当前边界

1. Agent 强依赖 Redis、Celery、DeepSeek 和 Milvus。FastAPI 正常并不代表 Agent 可运行，协作者需要同时确认 worker 已注册 `gapmind.run_agent` 和 `gapmind.validate_agent_code`。
2. Workspace RAG 依赖论文已经完成 PDF 解析、分块和向量化。只有元数据或 PDF 未处理完成时，不会产生 grounded 回答。
3. Research Plan Agent 会等待人工确认；只有确认后才生成正式 Research Plan。Code Generation Agent 又依赖正式计划，这个顺序是有意设计的安全 Gate。
4. 当前代码验证只做受限的 Python 语法检查，不安装生成项目的依赖，也不代表实验可以成功运行。
5. 当前所谓 Agent 是受控的专用工作流。后续若实现 Planner、Evidence、Critic、Gate 等角色协作，应复用现有 Run/Step/Artifact 协议，而不是并行建设第二套状态系统。
6. 前端构建成功，但主入口 chunk 约 1.30 MB，仍有 Vite 体积警告；不影响功能，但后续应做路由和依赖级拆包。
7. `backend/app/domains/agent/service.py`、Discover、Knowledge Graph 主服务/组件体积较大，后续多人并行修改时容易冲突，建议按检索、生成、持久化、状态转换继续拆分。
8. OpenAPI 类型文件已入库。任何接口字段变更后应运行 `npm run gen:api`，不要手工维护 `frontend/src/api/types/api.gen.ts`。

## 9. 合并后的建议验收流程

协作者合并或拉取后，建议按以下顺序进行一次最小端到端验收：

1. 执行三个数据库迁移并重启 FastAPI、Celery；
2. 进入一个已有解析和向量化论文的 Workspace；
3. 在 AI 助手中提问，确认回答出现引用且可打开原文定位；
4. 启动一次 Discover，分别验证“选择外部论文”和“跳过外部选择”；
5. 确认一个 Opportunity，检查其出现在研究中心 Portfolio；
6. 将 Opportunity 转为 Research Plan，确认计划出现在计划列表；
7. 在 AI 助手选择“生成研究计划”，确认草案停在人工确认状态；
8. 确认草案后，选择该计划启动“代码生成”；
9. 检查代码文件预览、单文件下载和 ZIP 下载；
10. 如显式开启 Sandbox，再验证 Docker 语法检查；默认关闭时不应影响前九步；
11. 进入知识工作台切换单列/双列，并在知识图谱中测试标签、搜索、悬停、节点详情和邻居展开；
12. 删除一条 Discover 历史记录，确认记录和其待处理候选不再进入正常统计。

## 10. 后续协作建议

- 优先围绕 PR #15 的完整链路做回归，不建议在合并前继续叠加新的 Agent 类型。
- 检索侧仍应关注完整 Retrieval Gate 中 Similar Work 和 Counter Evidence 的召回质量；Agent 输出质量最终受检索证据质量限制。
- 下一步最值得推进的是统一 Workspace 准备度、Evidence Manifest 和 Agent 运行可观测性，让用户明确知道“现在能做什么、为什么失败、下一步是什么”。
- 若多人并行开发，建议一人负责 Agent/Research Center，一人负责 Retrieval/Discover Gate，一人负责前端知识图谱与体验，尽量减少同时修改大型 Service 和 `KnowledgeGraph.tsx`。

---

如协作者只需要快速开始，请至少完成：拉取 `zwx` 或合并 PR #15 → `alembic upgrade head` → 重启 FastAPI/Celery → `npm run gen:api` → 启动前端。环境统一使用仓库内 `backend/.venv`，不需要使用 zwx 个人 Conda 环境。
