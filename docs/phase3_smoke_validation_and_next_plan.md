# Phase 3 Smoke 核验结果与后续验证、开发计划

> 核验日期：2026-07-29  
> 核验范围：依赖启动、Semantic Scholar 前端健壮性、PDF chunk、知识抽取与证据回链、
> Milvus 索引、Workspace Retrieval、LLM Judge  
> 关联文档：
> [`phase3_baseline_audit.md`](phase3_baseline_audit.md)、
> [`mvp_acceptance_and_sequence.md`](mvp_acceptance_and_sequence.md)、
> [`data_contracts_v1.md`](data_contracts_v1.md)

## 1. 结论摘要

本轮 Smoke Test 的**技术链路核验已经通过**：

- 3 篇真实论文均完成 PDF 解析、知识抽取、chunk 重建和 Milvus 重建索引；
- 当前 JSONL 中的每个 `chunk.text` 均与 `parsed_text[start_char:end_char]` 精确一致；
- 当前 Milvus chunk ID 集合与 JSONL 完全一致；
- KnowledgeItem 和 EvidenceSpan 均非空，EvidenceSpan 文本与来源 artifact 切片一致；
- Semantic Search、Similar Work 和 Counter Evidence 均能完成调用；
- LLM Judge 能对全部 10 条候选完成分批判别，不再静默返回
  `unknown / confidence=0.0`；
- 最终结构化验证为 `46 checks, 0 failures`；
- 后端回归测试为 `97 passed`，前端 Vitest 为 `2 passed`，前端生产构建成功。

但本轮结果**只证明链路正确，不证明检索质量达到 Stage 2 Gate**。当前 Counter Evidence
主要召回主张来源论文自身，只能得到 `overlaps`；Similar Work 仍包含参考文献和数据集描述
等低价值 chunk。进入 Opportunity Discovery 前，必须完成来源论文排除、论文级聚合、人工
gold 标注和外部新颖性核验。

## 2. Smoke 数据集

### 2.1 Workspace：Self-Interpretable GNN

Workspace ID：
`123100ea-e75b-4110-9048-1f5b92668c32`

论文一：

- 标题：Interpretable Prototype-based Graph Information Bottleneck
- Paper ID：`6dbc57ff-4a2d-4a9f-817c-63987037dcc6`
- 修复前历史 embed task 记录：33 chunks
- 当前 Paper、JSONL 和 Milvus：30 chunks

论文二：

- 标题：Self-Interpretable Graph Learning with Sufficient and Necessary Explanations
- Paper ID：`c1876121-d90b-41cc-8dce-878a0f076124`
- 修复前历史 embed task 记录：22 chunks
- 当前 Paper、JSONL 和 Milvus：20 chunks

### 2.2 Workspace：RAG / GraphRAG

Workspace ID：
`533c89cd-625f-45e7-8a44-cc737244273c`

论文三：

- 标题：RAG vs. GraphRAG: A Systematic Evaluation and Key Insights
- Paper ID：`8eb9634d-36fc-4a0a-b4c8-d61659740330`
- 修复前历史 embed task 记录：48 chunks
- 当前 Paper、JSONL 和 Milvus：45 chunks

历史 embed task 的计数是重建前的审计记录，不应被覆盖。`rebuild_paper_chunks.py` 直接同步
重建当前索引，因此验证脚本现在将旧计数显示为 `INFO`，并以实时 Milvus chunk ID 集合核验
当前状态。

## 3. 已发现问题及修复结果

### 3.1 `pymilvus` 启动依赖不兼容

现象：

- `marshmallow` 缺少 `__version_info__`，导致 `pymilvus/environs` 导入失败。

处理：

- 在 `backend/requirements.txt` 中约束 `marshmallow<4`。

结果：

- 后端可正常导入 Retrieval/Milvus 代码；
- 测试仍有来自旧依赖 API 的 deprecation warning，但不影响运行。

### 3.2 Semantic Scholar 页面因稀疏数据崩溃

现象：

- API 或旧 sessionStorage 数据中的 `authors`、`fieldsOfStudy`、
  `publicationTypes` 可能为 `null/undefined`；
- 页面访问数组 `.length` 时抛出异常。

处理：

- 在 API 客户端和搜索组件入口统一规范化论文对象；
- 非数组值转换为空数组，字符串和可空字段做类型收敛；
- sessionStorage snapshot 恢复时同样执行规范化。

结果：

- 前端 Vitest：`1 file, 2 tests passed`；
- `npm run build` 成功；
- 构建仍提示主 JS bundle 大于 500 kB，这是性能优化项，不阻塞当前 Smoke Gate。

### 3.3 Chunk 文本与 artifact 偏移不一致

现象：

- 原 chunker 会重新拼接段落和空白；
- `chunk.text` 与 `parsed_text[start_char:end_char]` 存在空白差异；
- 三篇旧论文均受影响。

处理：

- `_merge_paragraphs`、`_split_long_text`、`_add_overlap` 和
  `_merge_tiny_tail_chunks` 改为始终从原始 `parsed_text` 切片；
- 增加 chunk 精确切片回归测试；
- 新增 `scripts/rebuild_paper_chunks.py` 修复旧数据；
- 对三篇论文执行重建、删除旧 Milvus 向量并强制重新索引。

结果：

- 三篇论文全部通过 `all chunk texts equal parsed_text slices`；
- JSONL 数量分别为 30、20、45；
- 实时 Milvus chunk ID 分别与三份 JSONL 完全一致。

### 3.4 验证脚本错误使用历史 Task 计数

现象：

- 重建后 Paper chunk_count 已更新；
- 最近一次 Celery `embed_chunks` Task 是重建前的历史记录；
- 验证脚本因此错误报告 `embed counts match paper chunk_count` 失败。

处理：

- 历史 Task 计数不再作为当前索引状态的唯一真相；
- 计数不一致时输出 `INFO`；
- 新增实时 Milvus chunk ID 与当前 JSONL chunk ID 的集合一致性校验。

结果：

- 两篇 GNN 论文：`38 checks, 0 failures`；
- RAG/GraphRAG 论文：`19 checks, 0 failures`。

### 3.5 Judge 只处理前 8 条结果

现象：

- Counter Evidence 默认返回 10 条；
- `JudgementGateway` 每次最多处理 8 条；
- 后两条未经过 LLM 判断。

处理：

- Retrieval service 按 `8 + 2` 分批调用 Judge；
- 新增测试，确保 10 条结果全部进入 `llm_judged` 阶段；
- 任一 `unknown / confidence=0.0` 失败哨兵都会使响应进入 `degraded`。

结果：

- 10 条 Counter Evidence 均完成 LLM Judge。

### 3.6 Reasoning 模型耗尽 Judge 输出额度

现象：

- `deepseek-v4-flash` 会先生成 reasoning；
- 批量 8 条时固定 `max_tokens=512` 可能在生成最终 JSON 前耗尽；
- `message.content` 为空；
- 旧代码将空内容当作 `[]`，再静默补成全部
  `unknown / confidence=0.0`。

复现结果：

- 单条 Judge 正常：`supports / confidence=1.0`；
- 8 条、512 tokens：最终 content 为空；
- 8 条、2048 tokens：返回完整 JSON，usage 显示同时包含 reasoning tokens。

处理：

- token 预算改为 `max(1024, passage_count * 256)`；
- 8 条使用 2048，2 条使用 1024；
- 空 content 现在显式返回错误，不再伪装成合法 unknown；
- 日志增加 `finish_reason`；
- 新增 token 预算和空响应回归测试。

结果：

- Counter Evidence：`status=succeeded`；
- 10 条均为 `stage=llm_judged`；
- 展示结果为 `overlaps / confidence=0.9`，不再出现失败哨兵。

## 4. 最终自动核验结果

### 4.1 后端

执行：

```powershell
cd backend
python -m pytest tests -q
```

结果：

- `97 passed`
- 2 个第三方依赖 deprecation warning；
- 无测试失败。

### 4.2 前端

执行：

```powershell
cd frontend
npx vitest run
npm run build
```

结果：

- Vitest：`1 file passed, 2 tests passed`
- TypeScript 和 Vite production build 成功；
- 3071 modules transformed；
- 主 JS bundle 约 1.25 MB，gzip 后约 396 kB；
- 大 chunk warning 记为非阻塞性能债务。

当前 `package.json` 没有 `test` script，因此不能使用 `npm test`；后续应补充
`"test": "vitest"`，统一团队测试命令。

### 4.3 Pipeline

所有三篇论文均通过：

- Paper 存在且属于指定 workspace；
- `parse_status=parsed`；
- `extract_status=extracted`；
- parse、extract、embed 历史 Task 均存在且最近一次状态为 succeeded；
- parsed_text 可读取；
- chunk JSONL 存在；
- JSONL 数量等于当前 `paper.chunk_count`；
- chunk 文本等于 parsed_text 精确切片；
- Milvus chunk ID 等于当前 JSONL chunk ID；
- KnowledgeItem 非空；
- EvidenceSpan 非空；
- EvidenceSpan 文本等于来源 artifact 精确切片。

### 4.4 Retrieval

Semantic Search：

- 两个查询均为 `status=succeeded`；
- Top 1 分别命中目标论文；
- 结果未跨 workspace；
- 前五条整体与查询主题相关。

Similar Work：

- 两篇源论文均被正确排除；
- 能召回同 workspace 的另一篇相关论文；
- 由于当前 workspace 只有两篇论文，结果多样性不足；
- 部分高排位 chunk 来自参考文献、数据集描述或通用背景，相关性仍需优化。

Counter Evidence：

- `status=succeeded`；
- 10 条均经过 LLM Judge；
- 当前展示结果主要为 `overlaps / confidence=0.9`；
- 未发现真正的 `contradicts` 或 `qualifies`；
- 结果集中于 PGIB 来源论文本身，因此只能说明 Judge 链路可用，不能证明新颖性核验有效。

## 5. 人工核验结论

### 已确认

- Chunk 和 EvidenceSpan 的字符级 provenance 已达到本轮结构要求；
- Workspace 隔离有效；
- Semantic Search 对两个受控查询能正确定位目标论文；
- Similar Work 的源论文排除有效；
- Judge 可以稳定输出结构化角色分类和非零置信度；
- 失败时 `degraded` 与成功时 `succeeded` 的状态语义已经可区分。

### 尚未确认

- 尚未逐条判断所有 KnowledgeItem 的语义是否忠实于论文；→ **已做（RG-1 人工审查，回链 100%）**
- 尚未统计抽取 precision、recall 和 rejection 的真实质量；→ **已做（RG-1 五类判断 + P0 去重）**
- 尚未建立 Retrieval gold set，不能计算 Recall@10；→ **已建（RG-3 minimal_gnn_v1）**
- 尚未证明 Counter-Evidence Recall@10 达到 0.70；→ **minimal 语料 1.0（RG-8，2026-08-06）**
- 尚未证明 Similar Work Recall@10 达到 0.80；→ **minimal 语料 1.0（RG-8，2026-08-06）**
- 尚未完成 12 篇 Smoke Corpus；→ **仍待**（当前 9 篇 GNN explanation 论文，缺 evaluation/OOD 篇目）
- 尚未完成外部文献新颖性核验；→ **仍待（Stage 3）**
- 尚未证明 Opportunity 可以满足至少两篇独立全文证据的 Gate。→ **仍待（Stage 4）**

因此，当前应记录为：

> Phase 3 / Retrieval 技术 Smoke 通过；**minimal gold set（9 篇语料）质量 Gate 已通过**
> （Semantic/Similar/Counter Recall@10 = 1.0/1.0/1.0，leakage = 0，2026-08-06 完整版带 judge 实测）；
> 完整 12 篇 Smoke Corpus 的正式 Gate 尚未跑（需扩 corpus + 补检索 relevance 标注）。

## 6. 下一步验证计划

### V1：逐篇抽取质量人工审查

对三篇论文分别执行：

1. 从 Knowledge API 导出 method、task、dataset、claim、limitation；
2. 每篇至少抽查 5 个高价值 item；
3. 点击或按 offset 定位 EvidenceSpan；
4. 核对 canonical_name、type、content 与证据是否一致；
5. 核对 claim 是否超出原文含义；
6. 核对 limitation 是否是真实限制而非通用背景；
7. 查看该 run 的 extraction rejections，判断拒绝是否合理；
8. 记录 `正确 / 部分正确 / 错误 / 应拒绝但接受 / 应接受但拒绝`。

验收要求：

- 所有抽查 EvidenceSpan 保持 100% 精确回链；
- 不允许错误 claim 被当作 human-confirmed；
- 发现系统性错误时先修 prompt/schema，再扩展语料。

### V2：建立 Retrieval Gold Set

以 `demo_case_self_interpretable_gnn.md` 为主 Case，再增加至少 4 个轻量 Case：

1. 每个 Case 标注 3–5 个真实研究查询；
2. 为每个查询标注目标 paper 和关键 chunk；
3. 为 Similar Work 标注 paper-level relevant / irrelevant；
4. 为 Counter Evidence 标注 supports、overlaps、qualifies、contradicts、unknown；
5. 冻结 corpus version、chunk version、embedding model 和 reranker model；
6. 使用 `evaluation/retrieval/` 统一运行并保存结果。

验收要求沿用 Stage 2 Gate：

- Semantic Search Recall@10 ≥ 0.80；
- Similar Work Recall@10 ≥ 0.80；
- Counter-Evidence Recall@10 ≥ 0.70；
- workspace 泄漏为 0；
- 所有结果可回链到 Paper 和 artifact。

### V3：索引生命周期验证

必须补测：

1. 同一 paper 重复 embed 不产生重复 chunk；
2. chunk 版本变化后旧向量被完整删除；
3. paper 软删除后 Retrieval 不再返回该 paper；
4. workspace 软删除或归档策略符合契约；
5. embedding API、Milvus、reranker 分别失败时返回明确 failed/degraded；
6. Task、Paper 投影状态与实时 Milvus 状态不会互相冒充；
7. 从全新数据库执行迁移、上传、解析、抽取、索引和检索。

### V4：Counter Evidence 专项验证

准备至少三类主张：

- 可被明确支持的事实主张；
- 存在限定条件的性能或适用范围主张；
- 可能被既有工作反驳的“first / novel / outperform”主张。

每类至少 5 条，人工标注期望角色。重点检查：

- 来源论文是否被排除；
- 多个结果是否来自不同论文；
- `contradicts` 和 `qualifies` 是否优先展示；
- 没有反证时是否明确返回“已检索但未发现”，而不是伪造反证；
- Judge 失败是否返回 `degraded` 并保留可诊断错误。

### V5：外部新颖性核验

完成 Workspace Retrieval Gate 后：

1. 从 claim、method、task 和 limitation 构造外部 query；
2. 通过 Semantic Scholar 召回元数据和摘要；
3. 对候选进行 similar/overlap/qualify/contradict/unknown 判别；
4. 只为高价值候选下载开放 PDF；
5. 将 metadata-only 与 full-text evidence 明确区分；
6. 保存 query、候选、模型和时间戳快照；
7. 外部 API 失败时标记 `verification incomplete`。

## 7. 下一步开发计划

### D0：收尾当前 Smoke 基线

优先级：立即完成。

- 将本文作为当前核验记录；
- 在 `phase3_baseline_audit.md` 中增加指向本文的完成状态链接；
- 为前端增加统一 `npm test` script；
- 保留历史 embed Task，不篡改审计记录；
- 清理或忽略不应提交的 `.tsbuildinfo`、构建产物和本地备份；
- 按功能拆分 commit，确保 chunk 修复、Judge 修复、前端修复和文档可独立审查。

完成条件：

- 全新 checkout 可按文档复现测试；
- 工作区不包含误提交的生成文件和数据库备份。

### D1：完善 Retrieval 输入契约与来源排除

优先级：P0。

- Counter Evidence 请求增加 `source_paper_id` 或 `exclude_paper_ids`；
- Milvus recall 阶段尽早排除来源论文；
- API 响应记录实际应用的过滤条件；
- 增加 workspace 与 excluded paper contract tests；
- 更新 `data_contracts_v1.md` 和 API 文档。

完成条件：

- 新颖性主张的 Counter Evidence 不返回来源论文自身；
- 排除行为可从 `filters_applied` 审计。

### D2：论文级聚合、去重和多样性

优先级：P0。

- Similar Work 从 chunk 列表提升为 paper-level 结果；
- 每篇论文限制展示的高相似 chunk 数量；
- 对参考文献、页眉、作者信息等低价值区域降权；
- 使用 paper diversification，避免 Top 10 被单篇论文占满；
- 保留代表性 chunk 作为证据入口。

完成条件：

- Similar Work 结果以论文为主实体；
- Top 10 包含足够的 paper diversity；
- 不因重复 chunk 虚高 Recall。

### D3：Counter Evidence 排序语义

优先级：P0。

- Judge 后按 `contradicts → qualifies → supports/overlaps → unknown` 分组；
- 排序同时考虑 judgement、confidence、rerank score 和 paper diversity；
- 不把 `overlaps` 文案包装成“反证”；
- 结果为空时区分“未发现”“检索失败”“Judge 失败”。

完成条件：

- API/UI 的标签与证据角色一致；
- Discover Agent 可以安全区分没有反证和系统未完成核验。

### D4：检索评测与可复现性

优先级：P0。

- 固化 5 个 Case 和人工 gold；
- 实现 Recall@K、MRR、paper diversity、workspace leakage 指标；
- 记录 corpus、parser、chunk、embedding、reranker 和 judge 版本；
- 保存每次评测 JSON 报告；
- 将 Stage 2 Gate 纳入开发验收。

完成条件：

- 三项 Recall@10 达到既定阈值；
- 相同版本配置可以重复得到可比较结果。

### D5：外部检索接入 Discovery 证据链

优先级：Stage 2 通过后执行。

- 复用现有 Semantic Scholar 搜索、缓存、限流和 PDF 下载能力；
- 建立外部候选 snapshot，而不是只保存在临时前端状态；
- metadata-only 只用于候选筛选；
- 关键 Opportunity 结论必须回到 full-text evidence；
- 对 API 限流、无开放 PDF 和解析失败提供降级状态。

完成条件：

- 主 Demo Case 的 gold overlap/counter-evidence 能在外部 Top 10 召回；
- 每个 Opportunity 生成前至少执行一次外部核验。

### D6：进入 Opportunity / HITL

只有 D1–D5 达到 Gate 后才开始：

- Migration B：Opportunity、Version、Evidence、HumanDecision、ResearchPlan；
- Discover Agent 编排 Knowledge、Workspace Retrieval 和 External Verification；
- 关键结论必须有至少两篇独立全文证据；
- Opportunity 保持 candidate，必须经过人工 confirm/edit/reject/defer；
- confirmed Opportunity 才能生成 Plan。

## 8. 推荐执行顺序

```text
完成三篇抽取人工审查
→ 建立 Retrieval Gold Set
→ 来源论文排除
→ 论文级聚合、去重与多样性
→ Counter Evidence 角色排序
→ 索引生命周期与降级测试
→ 运行 Stage 2 指标评测
→ 扩展到 12 篇 Smoke Corpus
→ 外部新颖性核验
→ Opportunity / HITL / ResearchPlan
```

不要在 Stage 2 和 Stage 3 Gate 通过前开始 Opportunity 微调、GNN 排序、复杂多 Agent 或
Execute/Analyze/Publish/Respond 功能。

## 9. 当前 Go / No-Go

可以继续：

- 三篇论文的人工知识抽取审查；
- Retrieval 契约加固；
- gold set 和指标评测；
- 来源排除、论文级聚合、去重和降级路径开发。

暂不可以：

- 宣称 Retrieval 已达到质量指标；
- 使用当前结果证明 PGIB 的新颖性；
- 批量生成 Opportunity；
- 将 LLM 抽取结果直接作为训练 ground truth；
- 进入 Opportunity/HITL 的大规模实现。

最终判断：

> **GO：继续 Stage 2 Retrieval 加固与评测。**  
> **NO-GO：暂不进入 Opportunity Discovery 的正式生成阶段。**
