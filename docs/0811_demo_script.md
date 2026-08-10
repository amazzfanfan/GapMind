# 0811 演示剧本（W6-4）

> 日期：2026-08-11
> 作者：yx
> 用途：比赛 Demo 脚本打磨。基于真实端到端（`self-interpretable gnn` workspace，19 篇论文）验证的流程。
> 关联：`0811_e2e_results.md`（三次端到端结果）、`0809_freeze_version.md`（版本冻结）

---

## 演示主题

**基于学科领域大模型与多智能体协同的科研辅助系统** —— 从论文证据到可证伪研究计划与代码的完整链路。

## 前置（冻结版本）

- 语料：`self-interpretable gnn` workspace（19 篇，已解析/抽取/向量化）
- Prompt：`discover-v2` 全套；模型：deepseek-v4-flash（disable_thinking）+ BGE-m3 + reranker
- 环境：PostgreSQL / Redis / Milvus / S2（限流留意）+ Deepseek key

## 演示流程（~15 分钟）

### 步骤 1：研究准备度（2 分钟）— 展示"下一步去哪"
- **操作**：打开 `/workspaces/{id}/overview`
- **展示点**：
  - 六步进度条（文献→知识→发现→确认→计划→执行）全绿/部分
  - recommended next action（单一来源："运行 Discover 并确认机会"）
  - 统计数字与各页一致（readiness.counts）
- **台词**：系统把"能否发现 / 为何 / 下一步"统一成单一来源，HITL 铁律。

### 步骤 2：Workspace 检索 + RAG 对话（2 分钟）— 展示证据回链
- **操作**：知识工作台看图谱；AI 助手问"分布偏移下解释稳定性？"
- **展示点**：grounded 回答 + `[En]` 引用 + 原文定位；知识图谱（论文/方法/论断关系）
- **台词**：每个结论回链原文证据。

### 步骤 3：启动 Discover（多智能体交接流）（4 分钟）— 核心
- **操作**：Discover 页 → 新建任务（topic："Self-Interpretable GNNs"）
- **展示点**：
  - **Multi-agent handoff 卡片**逐步出现：planner → evidence → external_novelty → external_selection
  - 阶段进度条 + 状态
- **台词**：Planner 分解问题 → Evidence 装配证据 → ExternalNovelty 外部核验，阶段写 AgentStep，交接可见。

### 步骤 4：外部核验 + 全文核验（3 分钟）— 展示"找反证"
- **操作**：外部候选列表（S2 真实候选 + 角色）→ 勾选 2 篇导入全文核验
- **展示点**：
  - 61 候选，角色 similar/overlap/contradicts 判别
  - OA 下载 → 解析 → 抽取 → `verified + full_text`
  - 429 rate limit → 系统降级（succeeded_partial）不崩
- **台词**：metadata 不算全文证据；硬门槛 ≥2 独立全文。

### 步骤 5：机会候选 + Critic（2 分钟）— 展示"多智能体挑战"
- **操作**：看机会候选（2 个有区分度）
- **展示点**：机会详情 Evidence Passport 卡片（证据覆盖/全文来源/反证/人工状态）+ agent 交接 critic/gate 步骤
- **台词**：Critic 对抗性挑战 → 收窄/降权，弱机会不沉默丢弃。

### 步骤 6：HITL 决策（1 分钟）— 展示"人工确认"
- **操作**：机会确认/编辑确认/拒绝/延后
- **展示点**：4 决策 + Timeline 追溯（opportunity.deferred 事件）+ HumanDecision 历史
- **台词**：AI 只出候选，关键资产人工确认，决策可回溯。

### 步骤 7：研究计划（2 分钟）— 展示"可证伪计划"
- **操作**：研究计划 agent → 生成草案 → 确认
- **展示点**：计划字段（研究问题/假设/证伪标准/验证步骤）+ 证据引用 + 人工确认 Gate
- **台词**：计划必须可证伪、回链证据，人工确认后落库。

### 步骤 8：代码生成（2 分钟）— 展示"可复现实验"
- **操作**：代码生成 agent → 预览/下载
- **展示点**：7 文件项目（README/config/data/model/requirements）+ 预览
- **台词**：默认只预览/下载，不自动执行（安全铁律）。

### 步骤 9：结果分析 / 论文写作 / 审稿回复（W7，3 分钟）— 展示"全生命周期"
- **操作**：粘贴实验结果 → 结果分析 agent；选计划 → 论文写作；粘贴审稿意见 → 审稿回复
- **展示点**：
  - Analyze verdict（支持/部分/否定/证据不足）正确降级
  - Write 章节草稿 + [En] 回链
  - Respond 逐条回复 + 依据回链
- **台词**：确认计划 → 模拟实验 → 分析 → 草稿 → 回复一条链。

### 步骤 10：封版说明（1 分钟）
- **展示**：`0809_freeze_version.md` 冻结清单（语料/Prompt/模型/Schema）+ 3 次端到端记录
- **台词**：版本冻结，3 次全新 DB 跑通，可复现。

## 演示要点

- **多智能体交接流**是最大亮点（AgentStep 卡片逐步出现）
- **证据回链**贯穿（每个结论 [En] → 原文高亮）
- **HITL 铁律**：AI 只出候选，人工确认（计划/机会）
- **降级**：S2 429 / LLM 挂 / 证据不足 → 系统优雅降级（提前演练）

## 注意事项

- S2 限流：外部核验 12 query + 4 lookup 会超窗口，演示前预留/分批
- 演示前确认 workspace 已解析（避免现场等 pipeline）
- token：deepseek 烧 token 已用 `disable_thinking` 控制
