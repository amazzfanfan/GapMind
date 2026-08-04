# GapMind 数据契约 v1

> 版本：1.0.0
> 状态：比赛 MVP 冻结基线
> 更新日期：2026-07-25
> 产品语义依赖：[`mvp_core_spec.md`](mvp_core_spec.md)

本文只定义跨模块边界。模块内部可以调整实现，但不得改变字段语义、证据可追溯性和
Workspace 隔离规则。不兼容变更必须升级 major 版本。

## 1. 通用约定

- ID：UUID 字符串；外部论文 ID 明确标注来源，不伪装成本地 UUID。
- 时间：ISO 8601 UTC。
- 命名：`snake_case`。
- 文本：UTF-8。
- 所有本地对象必须携带并校验 `workspace_id`。
- 所有模型产出必须记录 `model_provider`、`model_name`、`prompt_version` 和 `run_id`。
- 所有证据必须说明 `evidence_level`：`full_text` 或 `metadata_only`。
- API/任务可以失败，但不得把空检索解释为“没有相关工作”。

## 2. Contract A：ParsedArtifact

一次 PDF 解析产生三种不可变 artifact：

- `parsed_text`：清洗后的纯文本，作为 chunk 字符偏移的规范来源。
- `parsed_markdown`：保留章节结构的文本，作为知识抽取与 EvidenceSpan 的规范来源。
- `chunk_index`：检索单位清单，不是证据原文来源。

每次重新解析必须创建新 artifact，并通过 `parser_version` 区分；禁止原地覆盖导致历史偏移
失效。

## 3. Contract B：Chunk

生产者：PDF parsing。消费者：Retrieval。

```json
{
  "schema_version": "1.0.0",
  "chunk_id": "uuid",
  "workspace_id": "uuid",
  "paper_id": "uuid",
  "source_artifact_id": "parsed_text artifact uuid",
  "source_artifact_kind": "parsed_text",
  "chunk_index": 5,
  "section": "Method",
  "subsection": "3.2 Formulation",
  "text": "Exact substring from parsed_text",
  "start_char": 12340,
  "end_char": 12890,
  "page_start": 3,
  "page_end": 3,
  "tokens_estimate": 480,
  "chunk_version": "v1",
  "created_at": "2026-07-25T10:00:00Z"
}
```

强约束：

- `text == parsed_text[start_char:end_char]`；若清理空白导致不能相等，生成即失败。
- `source_artifact_id` 永远指向 `parsed_text`，不指向 `chunk_index`。
- Milvus 主键使用 `chunk_id`，检索必须按 `workspace_id` 过滤。
- 更换 embedding 模型或维度必须新建 collection/version。
- 目标约 512 tokens、重叠约 50、最大 800；参数变化递增 `chunk_version`。

## 4. Contract C：ExtractionInput / ExtractionOutput

生产者：Artifact/Paper。消费者：Knowledge extraction。

### 4.1 输入

```json
{
  "schema_version": "1.0.0",
  "workspace_id": "uuid",
  "paper_id": "uuid",
  "artifact_id": "parsed_markdown artifact uuid",
  "artifact_kind": "parsed_markdown",
  "artifact_sha256": "hex",
  "text": "Complete parsed markdown",
  "title": "Paper title",
  "authors": ["Author"],
  "year": 2025
}
```

不得静默截断全文。上下文超限时使用带重叠的章节批次，并在汇总阶段去重；每个输出保留其
实际批次和 artifact 偏移。

### 4.2 输出

```json
{
  "schema_version": "1.0.0",
  "run": {
    "run_id": "uuid",
    "model_provider": "deepseek",
    "model_name": "model-name",
    "prompt_version": "extract_v2",
    "artifact_id": "uuid"
  },
  "entities": [
    {
      "local_ref": "entity-1",
      "type": "method",
      "canonical_name": "GNNExplainer",
      "aliases": ["GNN-Explainer"]
    }
  ],
  "mentions": [
    {
      "local_ref": "mention-1",
      "entity_ref": "entity-1",
      "paper_id": "uuid",
      "content": {
        "description": "Paper-specific description"
      },
      "confidence": 0.85,
      "evidence": {
        "artifact_id": "uuid",
        "artifact_kind": "parsed_markdown",
        "start_char": 100,
        "end_char": 180,
        "text": "Exact substring",
        "relation": "supports"
      }
    }
  ],
  "claims": [
    {
      "local_ref": "claim-1",
      "paper_id": "uuid",
      "statement": "Scoped claim",
      "claim_type": "positive",
      "scope": "small molecular graphs",
      "conditions": null,
      "confidence": 0.8,
      "evidence": {
        "artifact_id": "uuid",
        "artifact_kind": "parsed_markdown",
        "start_char": 300,
        "end_char": 380,
        "text": "Exact substring",
        "relation": "supports"
      }
    }
  ],
  "relations": [
    {
      "source_ref": "mention-1",
      "relation_type": "evaluates_on",
      "target_ref": "entity-2",
      "confidence": 0.7,
      "evidence_ref": "claim-1"
    }
  ]
}
```

校验要求：

- `entities`、`mentions`、`claims`、`relations` 必须为数组。
- 类型和 type-specific content 使用 Pydantic discriminated union 校验。
- evidence `text` 必须精确等于 artifact 切片。
- 所有引用必须能在同一输出或数据库中解析。
- Paper 关系不使用伪造的 Paper KnowledgeItem；持久化层直接关联 `papers.id`。
- 单次有效 Knowledge 写入在一个数据库事务中完成；失败不得留下部分 Knowledge 结果。
- item/relation 逐条校验；无效对象写入拒绝审计，不阻断同批次有效对象。
- 相同 `run_id` 重试必须幂等。

### 4.3 抽取拒绝审计

迁移 `0007` 后，每个被拒绝对象持久化为独立 `extraction_rejections` 记录：

```json
{
  "extraction_run_id": "uuid",
  "paper_id": "uuid",
  "batch_index": 0,
  "rejection_kind": "item|relation|output",
  "stage": "schema_validation|evidence_resolution|relation_resolution",
  "reason_code": "evidence_not_found",
  "reason_detail": "Safe diagnostic text",
  "item_type": "claim",
  "canonical_name": "Claim name",
  "raw_payload": {"type": "claim"},
  "evidence_preview": "Original evidence preview"
}
```

拒绝记录使用 `run + stage + payload + reason` 稳定指纹幂等。完整 Python traceback、API key
和 Worker 内部异常栈不得进入该契约。拒绝审计使用独立事务保存，因此全量校验失败时仍可
查询；有效 Knowledge 数据仍保持原子写入。迁移前历史 run 只有计数，无法回填对象详情。

## 5. Contract D：RetrievalResponse

生产者：Retrieval。消费者：Discover/UI。

```json
{
  "schema_version": "1.0.0",
  "request_id": "uuid",
  "workspace_id": "uuid",
  "query": "claim or research question",
  "purpose": "semantic|similar_work|counter_evidence",
  "status": "succeeded|degraded|failed",
  "items": [
    {
      "result_id": "uuid",
      "source_scope": "workspace|external",
      "evidence_level": "full_text|metadata_only",
      "paper_id": "local uuid or null",
      "external_paper_id": "S2 ID or null",
      "paper_title": "Title",
      "paper_year": 2025,
      "chunk_id": "uuid or null",
      "artifact_id": "uuid or null",
      "section": "Discussion",
      "text": "Retrieved text or abstract",
      "score": 0.87,
      "retrieval_stage": "candidate_recall|reranked|llm_judged",
      "judgement": "supports|overlaps|qualifies|contradicts|unknown",
      "judgement_confidence": 0.72
    }
  ],
  "total": 10,
  "latency_ms": 45.2,
  "filters_applied": {},
  "error": null
}
```

强约束：

- 向量相似度只能产生 `candidate_recall`，不能直接宣称反证。
- `counter_evidence` 必须经过 rerank 或 LLM/NLI 判别，并允许 `unknown`。
- 外部摘要结果使用 `metadata_only`；关键 Opportunity 结论不能只依赖该级别。
- 检索失败返回 `status=failed` 和结构化 error；不得伪装成成功的空列表。
- Workspace 本地检索必须严格过滤 `workspace_id`。
- **来源论文排除（RG-2 / D1）**：
  - `counter_evidence` 请求必须携带 claim 的 `source_paper_id`（或等价的 `exclude_paper_ids`）；
    来源论文必须**在 Milvus recall 阶段被排除**（filter 表达式 `paper_id not in [...]` 下推），
    不能只做返回后的 post-filter——否则来源论文自身的 chunk 会挤掉真正的反证。
  - `similar_work` 恒排除源 `paper_id`，即使调用方未显式传 `exclude_paper_ids`。
  - 每次响应 `filters_applied` 必须记录实际生效的 `excluded_paper_ids`（排序后的 UUID 列表），
    供审计：排除行为可复现。
  - 排除行为是**召回语义的一部分**：不传排除时返回来源论文不构成"未发现反证"；只有
    检索成功且排除后无命中，才算 `succeeded` 空结果。
  - 服务层对返回结果保留一道防御性 post-filter（belt-and-suspenders），防止特定 Milvus
    版本 filter 语法回归把来源论文漏进来。

## 6. Contract E：ExternalPaperCandidate

```json
{
  "schema_version": "1.0.0",
  "candidate_id": "uuid",
  "discover_run_id": "uuid",
  "provider": "semantic_scholar",
  "external_paper_id": "S2 ID",
  "title": "Title",
  "abstract": "Abstract or null",
  "year": 2025,
  "open_access_pdf_url": "URL or null",
  "relevance_score": 0.82,
  "candidate_roles": ["similar_work", "counter_evidence"],
  "status": "external_candidate|metadata_imported|pdf_pending|parsed|indexed|extracted",
  "selected_reason": "Why this paper needs full-text verification"
}
```

只有进入 `metadata_imported` 后才创建本地 Paper；MVP 仅对少量高价值候选进入全文处理。

## 7. Contract F：OpportunityProposal

```json
{
  "schema_version": "1.0.0",
  "id": "uuid",
  "workspace_id": "uuid",
  "agent_run_id": "uuid",
  "version": 1,
  "title": "Scoped opportunity",
  "problem_statement": "Problem",
  "research_scope": "Scope",
  "supporting_evidence": [
    {
      "paper_id": "uuid",
      "evidence_span_id": "uuid",
      "claim": "What this evidence supports"
    }
  ],
  "similar_work": [
    {
      "paper_id": "uuid or null",
      "external_paper_id": "S2 ID or null",
      "evidence_level": "full_text",
      "difference": "Specific difference"
    }
  ],
  "counter_evidence": [],
  "why_existing_work_is_insufficient": "Gap after overlap analysis",
  "candidate_research_question": "Question",
  "candidate_hypothesis": "Falsifiable hypothesis",
  "candidate_validation_plan": {
    "datasets": [],
    "baselines": [],
    "metrics": [],
    "steps": [],
    "falsification_criteria": []
  },
  "open_risks": [],
  "scores": {
    "novelty": 3,
    "feasibility": 4,
    "significance": 3
  },
  "confidence": 0.72,
  "evidence_coverage": {
    "independent_paper_count": 3,
    "full_text_evidence_count": 4,
    "metadata_only_count": 1
  },
  "status": "candidate",
  "created_at": "2026-07-25T10:00:00Z"
}
```

硬门槛：

- 至少 2 篇独立论文的 full-text supporting evidence；
- `similar_work`、`counter_evidence`、风险和 falsification criteria 字段必须存在，可为空但
  必须解释检索状态；
- 不能把 Future Work 或 Limitation 作为唯一依据；
- 缺少外部核验时只能输出低置信度 `candidate`，并明确 verification gap。

## 8. Contract G：HumanDecision / ResearchPlan

```json
{
  "decision_id": "uuid",
  "workspace_id": "uuid",
  "opportunity_id": "uuid",
  "opportunity_version": 1,
  "action": "confirm|edit_confirm|reject|defer",
  "edited_content": null,
  "reason": "optional",
  "review_condition": "optional for defer",
  "actor": "user",
  "created_at": "2026-07-25T10:00:00Z"
}
```

`edit_confirm` 必须先创建 Opportunity 新版本，再让 decision 指向新版本。ResearchPlan 必须
记录 `source_opportunity_id` 和 `source_opportunity_version`，并包含可证伪假设、数据集、
baseline、metric、步骤、资源约束和 falsification criteria。

## 9. 版本与交付

- JSON/JSONL 顶层必须携带 `schema_version`。
- Contract fixture 放入测试目录，生产者和消费者都用同一 fixture 做 contract test。
- 旧 [`data_contracts.md`](data_contracts.md) 仅供历史追溯。
- v1 首个实现前允许补充可选字段；重命名、删除或改变字段语义必须发布 v2。
