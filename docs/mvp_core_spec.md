# GapMind MVP 核心闭环规格

> 状态：开发前冻结基线（v1）
> 更新日期：2026-07-25
> 适用范围：比赛 MVP

本文档是核心产品语义的单一事实来源。`plans.md` 负责路线图，`data_contracts_v1.md`
负责跨模块数据格式，具体实现不得与本文的边界和对象语义冲突。

## 1. P0 闭环与边界

比赛 MVP 只要求跑通以下闭环：

```text
研究主题 / 用户论文
→ PDF 解析与证据文本
→ 论文级结构化陈述
→ Workspace 检索
→ 外部文献候选核验
→ Research Opportunity Proposal
→ 用户确认 / 编辑 / 拒绝 / 延后
→ 可编辑 Research Question / Hypothesis / Validation Plan
```

当前不进入 P0：自动执行实验、实验分析、论文写作、审稿回复、复杂协作、GNN
排序和抽取模型微调。微调可以并行研究，但不得阻塞上述闭环。

### 1.1 两个检索边界

- **Workspace 是研究上下文边界**：用户选择的论文、约束、目标、决策和长期资产均归属
  Workspace。
- **Workspace 不是新颖性边界**：系统不得仅根据已上传论文声称“领域中无人研究”。
- Discover 先用 Workspace 语料产生线索，再通过 Semantic Scholar 等外部来源检索
  元数据和摘要；只对高相关、开放获取的关键候选下载或要求用户补充 PDF，并做全文核验。
- 无法获取全文时，外部摘要只能标为 `metadata_only` 证据，不能承担关键结论的唯一支撑。

## 2. 核心对象语义

### 2.1 Paper

Paper 是独立领域对象，不复制为 KnowledgeItem。它保存书目信息、来源、PDF 和解析状态，
并作为所有论文级陈述与证据的来源。

外部候选进入本地后的状态：

```text
external_candidate
→ metadata_imported
→ pdf_pending
→ parsed
→ indexed
→ extracted
```

`external_candidate` 可以只存在于一次 Discover Run 的快照中；用户导入或系统选中进行全文
核验后，才创建本地 Paper。MVP 不自动批量下载全部搜索结果。

### 2.2 CanonicalEntity

Method、Task、Dataset 是可跨论文复用的规范实体。一个 Workspace 内同一规范实体只保存一份，
只承载稳定身份信息，例如规范名、别名和实体类型。它不直接保存“某篇论文如何描述该实体”。

### 2.3 PaperMention

PaperMention 表示“某篇论文如何提及或描述某个规范实体”。同一 CanonicalEntity 可以拥有
多篇论文的多个 Mention。论文特有的描述、输入输出、使用场景和抽取置信度属于 Mention，
不能覆盖规范实体。

### 2.4 Claim

Claim 是带范围和条件的论文级陈述，不应按相似文本直接合并。Claim 可以引用
CanonicalEntity，并由一个或多个 EvidenceSpan 支持、限定或反驳。跨论文 Claim 的等价、
蕴含和冲突关系必须显式保存，不能通过覆盖旧记录表达。

### 2.5 EvidenceSpan

EvidenceSpan 是不可变证据锚点，必须同时记录：

- `paper_id`
- `artifact_id`
- `artifact_kind`
- `artifact_version`
- `start_char` / `end_char`
- `text`
- `relation`：`supports` / `qualifies` / `contradicts`

字符偏移必须针对 `artifact_id` 指向文件的原始字符串计算。MVP 统一使用
`parsed_markdown` 作为知识抽取和证据展示的规范文本；`parsed_text` 与 chunks 只用于检索。
若未来切换规范文本，必须生成新 artifact/version，不得复用旧偏移。

### 2.6 Opportunity 与 ResearchPlan

Opportunity 和 ResearchPlan 是具有独立生命周期、版本和用户决策的领域对象，不作为普通
KnowledgeItem JSON 混存。它们可以引用知识实体、Claim 和 EvidenceSpan。

## 3. 推荐逻辑关系

```text
Paper 1 ──< PaperMention >── 1 CanonicalEntity
Paper 1 ──< Claim
Paper 1 ──< EvidenceSpan >── 1 PaperMention/Claim
Claim >── supports/qualifies/contradicts ──< Claim
Opportunity >── OpportunityEvidence ──< EvidenceSpan/ExternalEvidence
Opportunity 1 ──< OpportunityVersion
Opportunity 1 ──< HumanDecision
Opportunity 1 ── 0..1 ResearchPlan
```

现有 `knowledge_items` 可在下一次迁移中演进为规范实体和论文级陈述的承载结构，但在迁移
设计冻结前，禁止继续依赖 `(workspace_id, type, canonical_name)` 覆盖旧内容。

## 4. Opportunity 最小契约

每个候选必须包含：

- `title`
- `problem_statement`
- `research_scope`
- `supporting_evidence`：至少来自 2 篇独立论文
- `similar_work`
- `counter_evidence`
- `why_existing_work_is_insufficient`
- `candidate_research_question`
- `candidate_hypothesis`
- `candidate_validation_plan`
- `open_risks`
- `novelty_score`、`feasibility_score`、`significance_score`
- `confidence`
- `evidence_coverage`
- `status`
- `agent_run_id`、Prompt/模型/语料版本

Opportunity 必须被表述为 Proposal。仅由单篇 Future Work、单篇 Limitation 或关键词拼接
产生的结果不合格。

## 5. HITL 状态机

```text
candidate
├─→ confirmed
├─→ edited_confirmed
├─→ rejected
└─→ deferred ─→ candidate

confirmed / edited_confirmed ─→ superseded
```

- 所有用户编辑创建新版本，旧版本不可变。
- 每次确认、编辑确认、拒绝和延后均创建 HumanDecision，并写 Timeline。
- `rejected` 需要可选原因；`deferred` 需要可选复查条件。
- 只有 `confirmed` 或 `edited_confirmed` 可以生成 ResearchPlan。

## 6. ResearchPlan 最小结构

- Research Question
- Falsifiable Hypothesis
- Scope and Assumptions
- Datasets / Baselines / Metrics
- Validation Steps
- Expected Supporting Result
- Falsification Criteria
- Risks and Resource Constraints
- Linked Opportunity Version

生成结果仍是 Proposal，用户可以编辑并确认；MVP 不自动运行计划。

## 7. 当前架构决策

1. 保持模块化单体、PostgreSQL、Milvus、Redis 和 Celery，不引入新基础设施。
2. Discover 仍是唯一需要 Agent 式编排的 P0 能力；抽取、检索、状态转换是普通 Service/Task。
3. Opportunity、ResearchPlan、HumanDecision 建议使用独立表和领域服务。
4. CanonicalEntity 与 PaperMention 的物理表设计在实现前单独评审并通过 Alembic 迁移落地。
5. 所有 LLM 产出先进入候选态，不能直接成为长期事实。
