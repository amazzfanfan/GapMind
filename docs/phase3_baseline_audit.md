# Phase 3 知识抽取基线审查

> 审查日期：2026-07-25
> 范围：当前未提交的知识抽取、Markdown artifact 和自动任务串联
> 原始结论：可以继续做 Smoke Test，但不应在旧写入模型上批量生产训练数据。

## 实施更新（2026-07-25）

本审查提出的 Stage 1 修复已落地：

- Migration `0006_knowledge_provenance` 增加 CanonicalEntity、ExtractionRun、paper-scoped
  KnowledgeItem、提取状态和 artifact 版本字段；
- 抽取改为严格 Pydantic schema、精确证据校验、单事务写入和 run 内幂等；
- 同名实体不再覆盖，跨论文保存独立 Mention；
- 长文改为带重叠的章节优先分批，不再静默截断；
- Paper 关系由 `paper_id + Mention` 隐式表达，Prompt 不再生成无法持久化的 Paper 边；
- chunk 统一引用 parsed_text source artifact；
- 增加显式 extraction trigger/retry API；
- 新增事务回滚、幂等、跨论文实体、证据偏移、长文覆盖和 trigger 测试。

进入批量抽取前仍需：在 PostgreSQL 应用迁移、用 3 篇真实论文做 LLM Smoke Test，并人工
核对关键 EvidenceSpan。以下审查项保留为设计背景和回归依据。

## 拒绝审计更新（2026-07-26）

- Migration `0007_extraction_rejections` 增加逐对象拒绝审计表和稳定指纹幂等约束；
- schema、evidence、relation 改为逐条容错验证，有效对象不再被同批错误拖垮；
- 全量失败时拒绝记录通过独立事务保留，Task payload/result 均可定位 run；
- 新增 workspace 隔离、分页过滤 API，以及 Task 页面拒绝详情弹窗；
- 只记录完整被拒绝对象，不保存整次 LLM 原始响应或内部异常栈。

`0007` 之前的 extraction run 只有聚合计数，历史拒绝对象无法回填；重新抽取后才会产生
可查询明细。

## 1. 必须先修复

### P1：一次异常会留下部分知识数据，并让 Task 停在 running

`KnowledgeService.upsert_item()`、`create_evidence_span()` 和 `create_relation()` 每写一条就
`commit()`。`_write_extraction()` 在循环中构造 Pydantic 对象，任意一个非法类型或数据库
错误都会发生在此前多次提交之后。异常没有被 `_run_extract()` 捕获并转为 `_fail()`，因此
Celery 任务失败时业务 Task 可能仍是 `running`。

处理要求：

- 整次 extraction run 使用一个事务；
- service 写方法只 `add/flush`，由任务入口统一 commit；
- 任意异常 rollback，并把 Task/Paper extraction 状态写成 failed；
- 错误状态更新使用独立、可靠的事务。

### P1：同名实体跨论文互相覆盖

`upsert_item()` 使用 `(workspace_id, type, canonical_name)` 查找已有记录，并覆盖
`content`、`source_provenance` 和 `confidence`。第二篇论文提及 GNNExplainer 时会抹掉第一篇
论文的描述和主来源，版本号也被误用为“新论文覆盖次数”。

处理要求：按 [`mvp_core_spec.md`](mvp_core_spec.md) 拆分规范实体与论文级 Mention/Claim。
在迁移完成前，禁止用当前 upsert 批量导出微调 ground truth。

### P1：重试不幂等，会重复追加 EvidenceSpan 和 Relation

KnowledgeItem 虽然被 upsert，但每次任务重试都会无条件创建新的 evidence 和 relation。
相同论文重复解析或 Celery 重投后，计数和图谱边会持续膨胀。

处理要求：

- 每次抽取生成稳定 `extraction_run_id` 和 item key；
- 同一 run 重投使用幂等键；
- 新 run 成功后再原子切换 active version；
- EvidenceSpan 至少对目标、artifact、offset、relation 建唯一约束。

### P1：Paper 关系被抽取后全部丢弃

Prompt 明确要求 `paper --proposes/addresses/evaluates_on--> ...`，但写入代码遇到任一
`paper` 端点即 `continue`。因此最重要的 Paper→Method/Task/Dataset 图关系永远不会出现，
与文档和前端图谱目标不一致。

处理要求：Paper 保持独立领域对象。对 method/task/dataset 使用带 `paper_id` 的 Mention
表达 Paper 关系；不要创建重复的 Paper KnowledgeItem。

### P1：40,000 字符静默截断会系统性漏抽论文后半部分

`build_user_prompt()` 只发送前 40,000 字符。长论文的实验、Discussion、Limitation 和
Conclusion 常位于后半部分，恰好是 Opportunity 需要的高价值内容。当前 Task 结果也不记录
发生过截断。

处理要求：按章节分批抽取并做文档级汇总去重；每批保留原 artifact 偏移。不得把截断结果
标记为完整论文抽取。

### P1：LLM 输出未做契约级校验

当前仅检查 JSON 能解析且存在 `items`。没有验证 type-specific content、relations 数组、
枚举、workspace/paper 一致性，也没有验证 `evidence_text` 是否等于 artifact 对应切片。
错误偏移会直接写库，破坏 GapMind 最核心的证据回链。

处理要求：使用 discriminated-union Pydantic schema；写库前一次性验证全部输出和引用；
证据必须满足 `text == artifact[start_char:end_char]`，不匹配时允许通过精确字符串搜索修复
唯一匹配，否则拒绝该 item。

## 2. 应在接 Retrieval 前修复

### P2：artifact 字段命名与实际语义冲突

抽取读取并引用的是 `parsed_markdown`，但 `source_provenance` 键仍写成
`parsed_text_artifact_id`。后续消费者会在纯文本中套用 Markdown 偏移。

处理要求：统一为 `artifact_id` + `artifact_kind=parsed_markdown` + `artifact_version`。

### P2：Chunk 的 artifact 引用不一致

chunk 在创建时 `artifact_id=""`；保存 `chunk_index` 文件后才把内存对象改为
`chunk_index_artifact.id`。因此数据库中的 chunk_index artifact 含空 ID，额外导出的 JSONL
含 chunk_index ID；同时字符偏移实际来自 parsed_text。三个语义互相冲突。

处理要求：先创建 parsed_text artifact，再生成 chunk；统一输出
`source_artifact_id=parsed_text_artifact.id`。chunk_index artifact 只是清单容器。

### P2：代码注释声明 Paper extraction 状态，但模型没有对应字段

任务文件声明 `pending → extracting → extracted / failed`，实际 Paper 模型没有
`extract_status`、`extracted_at` 或 active run。前端无法区分“尚未抽取”“正在抽取”和
“抽取失败”，也无法安全重试。

处理要求：增加 Paper extraction 状态和 active extraction run 引用，或以 ExtractionRun
聚合状态并由 API 投影；二者选一，不重复保存两套真相。

### P2：自动 dispatch 失败后没有可用的人工补偿入口

parse task 把 spawn extraction 作为 best-effort，并声称用户之后可以手动触发，但当前没有
对应 API。Redis/Celery 短暂失败会让 Paper 永久停在“已解析但未抽取”。

处理要求：提供幂等的 extraction trigger/retry API，或建立 reconciliation job；比赛 MVP
优先显式 trigger/retry。

### P2：缺少 Phase 3 测试

现有 `test_knowledge_api.py` 只测试空列表和 404，没有覆盖 JSON 校验、证据偏移、事务回滚、
幂等重试、同名实体跨论文和自动 dispatch。

最低新增测试：

1. 完整合法输出原子写入；
2. 第 N 个 item 非法时零知识行落库且 Task failed；
3. 相同 run 重试不重复；
4. 两篇论文提及同一实体时保留两个 Mention；
5. evidence offset 与 Markdown 精确匹配；
6. 长论文分批后仍抽取 Conclusion/Limitation；
7. dispatch 失败后可以手动重试。

## 3. 迁移决定

需要 Alembic 迁移。推荐拆成两个小迁移，避免把 Knowledge 修正与 Opportunity/HITL 一次完成。

### Migration A：Knowledge provenance（下一步）

- 新建 `canonical_entities`：`workspace_id`、`type`、`canonical_name`、`aliases`、
  `normalization_key`、状态与时间戳。
- `knowledge_items` 明确为论文级 Mention/Claim/Limitation，新增：
  `paper_id`、可空 `canonical_entity_id`、`extraction_run_id`、`item_key`。
- 新建 `extraction_runs`：paper/artifact/prompt/model/schema/status/error/started/finished。
- EvidenceSpan 增加 `artifact_kind`、`artifact_version`，移除业务上对 `chunk_index` 的依赖。
- 增加幂等与唯一索引；迁移已有 Smoke 数据时保留原行并标记 legacy source。

这是最小可行方案：不需要把每一种知识类型拆表，也不需要图数据库。

### Migration B：Opportunity + HITL + Plan（抽取稳定后）

- 独立 `opportunities`、`opportunity_versions`、`opportunity_evidence`；
- 独立 `human_decisions`；
- 独立 `research_plans`，引用确认的 opportunity version；
- Timeline 继续使用通用 subject 指针，不新增事件子表。

## 4. 建议修复顺序

1. 明确 Migration A schema 和回填策略；
2. 修正 chunk source artifact；
3. 增加严格 extraction schema 和证据校验；
4. 将写入改为单事务并实现 run 幂等；
5. 章节批处理替代静默截断；
6. 增加 extraction status、trigger/retry API；
7. 补齐 Phase 3 测试；
8. 通过 3 篇 Smoke Paper 后再批量扩展语料。

## 5. Go / No-Go 门槛

满足以下条件后才进入 30–50 篇批量抽取：

- 任一失败不产生部分知识数据；
- 同一 run 重试结果不重复；
- 同一实体的多论文 Mention 不互相覆盖；
- 抽查 evidence 回链正确率达到 100%（Smoke Set 的关键证据）；
- 长论文的关键章节没有因上下文限制静默丢失；
- 每篇 Paper 可观察 extraction 状态并可人工重试；
- contract tests 与 Phase 3 测试通过。
