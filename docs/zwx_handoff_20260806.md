# 交付记录：2026-08-03 ~ 08-06（给 zwx）

> 作者：yx　日期：2026-08-06
> 目的：同步这 4 天的完成内容，供 zwx review + 对齐后续计划。后续 TODO 详细清单见 `docs/research_assistant_completion_plan.md` §8。

---

## 一、总览

| 日期 | 工作块 | 关键产出 |
|---|---|---|
| 08-03~04 | 架构重构 S1-S8 | 异常集中化 / Protocol ports / discover+worker 子模块化 / TS 类型自动生成；244 测试 |
| 08-04 | Retrieval Gate RG-2~RG-7 | 来源排除 / 评测框架 / Similar 聚合 / Counter 排序 / 索引生命周期 / V4 专项；229 测试 |
| 08-05 | 抽取质量 + P0 去重 | 人工审查 / 精确去重 / LLM 空输出修复；244 测试 |
| 08-06 | 完整 demo Gate + Stage 3 外部核验 | 18 篇 corpus / minimal Gate PASS / 外部角色判别 + 多 query 检索 + Gate 验证；257→265 测试 |

---

## 二、按工作块详情

### 2.1 架构重构（08-03~04）— 对齐 Mavis 评审

- 全局异常 handler 集中化：`core/exception_handlers.py` + `core/errors.py`（11 测试）
- router 减 ~260 行重复样板；workspace 404 用 router-level dep
- **Protocol ports**：`discover/ports.py`（Retrieval/ExternalSearch/LLM 3 个 Protocol）+ adapters，discover 单测可注入 fake，不依赖 Milvus/Deepseek/S2
- discover 子模块化：`exceptions.py`（7 异常）+ `opportunity_workflow.py`（13 方法）
- worker 子模块化：`extraction/{batching,evidence_rebaser,llm_caller}.py`
- actor 注入：`get_current_user` 读 `X-User-ID`
- 前端 TS 类型从 OpenAPI 自动生成（`npm run gen:api`）
- 文档：`architecture-refactor-plan-2026-08-04.md` + `contributing.md`

### 2.2 Retrieval Gate RG-2~RG-7（08-04）— **与 zwx 检索代码直接相关**

| RG | 内容 | 关键点 |
|---|---|---|
| RG-2 | 来源论文排除契约化 | `exclude_paper_ids` 下推到 **Milvus recall 阶段**（filter `paper_id not in [...]`），非 post-filter |
| RG-3 | 评测框架 | `evaluation/retrieval/`：gold_set.py / metrics.py / run_eval.py；退出码 0=全 PASS |
| RG-4 | Similar Work 论文级聚合 | 低价值段落（References/Appendix 等）丢弃 + 每论文 cap=2 + rerank 前多样化 |
| RG-5 | Counter Evidence 角色排序 | `RetrievalResultItem.judgement` 收紧 Literal + 角色优先级排序 + `empty_reason` 三态 |
| RG-6 | 索引生命周期 | `PaperService.soft_delete` 传播到 Milvus；conftest 加 `_stub_milvus` autouse |
| RG-7 | Counter 专项验证 | `counter_evidence_v4.json` 15 条主张 + `verify_counter_evidence.py` 5 个行为不变量 |

### 2.3 抽取质量 + P0 去重（08-05）

- **RG-1 人工审查**：三篇论文 103 个 evidence spans 回链字符级 100%；发现 claim/limitation 级重复问题
- **P0 精确去重**：`extraction/dedup.py`（dedup_exact + content_signature），接入抽取主循环；静态验证 PGIB 24→24、SunnyGNN 17→14、RAG 62→61
- **LLM 空输出修复（生产 bug）**：deepseek-v4-flash 长输入把 16384 token 全烧在 reasoning（65431 字符 CoT）→ content 空。修复：`chat_completion(disable_thinking=True)` → `extra_body={"thinking":{"type":"disabled"}}`。20K prompt 从 content 0 → 23773 字符 valid JSON
- 分层方案：P0 精确（已完成）/ P1 语义（feature flag）/ P2 prompt 收敛 —— `docs/knowledge_dedup_fix_plan.md`

### 2.4 完整 demo Gate + 检索评测（08-06）— **zwx 重点看**

- **corpus 扩到 18 篇**：从 S2 导入 8 篇 + GSAT，手动补 2 篇 arXiv PDF
- **修 SubgraphX 解析 bug**：arXiv 标题 11.95pt 被旧阈值 `>=12.0` 拒判 → 只 4 appendix chunks。改 `>=11.5` → 31 chunks
- **minimal Gate（9 篇）PASS**：recall 1.0/1.0/1.0 + leakage 0
- **完整 demo Gate（18 篇）首跑**：

| benchmark | 完整 demo | 阈值 | 状态 |
|---|---|---|---|
| Semantic Search Recall@10 | 1.0 | 0.80 | ✅ |
| Similar Work Recall@10 | 0.778 | 0.80 | ❌ 差 0.02 |
| Counter Evidence Recall@10 | 0.667 | 0.70 | ❌ 差 0.03 |
| leakage | 0 | 0 | ✅ |

- 未召回 4 篇（DIR/PGM-Explainer/Zorro/GOOD）→ 建议调 over-fetch（4x→6x）或 reranker 权重
- **运行注意**：`run_eval` 必须从 `backend/` 跑（.env 在 backend）
- 报告：`docs/retrieval_gate_report.md`

### 2.5 Stage 3 外部新颖性核验（08-06）

- **外部候选角色判别**：heuristic（similar/unknown）+ LLM 批量精化（similar/overlap/qualify/contradict/unknown，8/batch）
- **多 query 外部检索**：`_build_external_queries`（研究轴 LLM 分解 + 方法名 grounding + 精确名查找）+ **轮转合并**（原 primary-first 会隐藏附加 query 发现）+ 候选按 external_paper_id 去重
- **Stage 3 Gate 验证基础设施**：`evaluation/external/` gold set（7 篇 corpus 外真实论文）+ runner + `docs/external_novelty_gate_report.md`
- 结果：管线层 curated query recall@10=**0.857 PASS**；auto 生成层 0.0→0.286（MRR 0.5，GIB/IRM 经精确名查找前置 top-3）

---

## 三、系统现状（能做什么）

- 导入论文 → 解析 → 知识抽取（方法/任务/数据集/主张/局限）→ 证据字符级回链
- Workspace 检索：语义搜 / 相似工作 / 反证（来源排除 + 角色排序）
- Discover Run（异步）：内部证据 + 外部 S2 核验 → 机会候选（多候选）
- HITL：确认 / 编辑确认 / 拒绝 / 延后 + Timeline + 版本 diff → 研究计划
- 前端 DiscoverPage 完整（run / 外部候选 / 机会 / 决策 / 证据回链 / 转计划）
- 265 后端测试全过

---

## 四、后续计划（详细 TODO 见 `research_assistant_completion_plan.md` §8）

```
#26 MA 多智能体骨架（对齐比赛题目"多智能体协同"）→ #27 W1 外部全文闭环 → #28 W2 机会质量
   └→ #29 W4 前端（并行）→ #30 W7 全生命周期 agent（分析/写作/审稿）
                    ↘ #31 W5 端到端验收 → #32 W6 封版
```

比赛题目：**基于学科领域大模型与多智能体协同的科研辅助系统**。当前是单管线，需重构为有界多智能体（Orchestrator + Evidence/ExternalNovelty/Critic/Opportunity/Gate/Plan agent）。

---

## 五、给 zwx 的 review 点 / 可参与点

**建议 review（检索相关）**：
1. `evaluation/retrieval/` 评测框架——zwx 可直接用来评估自己的 Milvus 检索
2. RG-2 来源排除的下推实现（`milvus_client.search` 的 `exclude_paper_ids` filter）
3. RG-4 Similar 聚合、RG-5 Counter 排序的 service 层逻辑
4. `docs/retrieval_gate_report.md` 完整 demo Gate 的 4 篇未召回论文——**调召回（over-fetch 或 reranker）是检索侧下一个任务**

**可参与点**：
- 完整 demo Gate 达标（similar 0.778→0.80、counter 0.667→0.70）——如果你那边有 Milvus 调优空间
- W2 机会质量依赖检索结果，检索 quality 上去了 W2 更好过

**注意**：检索性能调优暂时搁置（我这边优先做多智能体重构），demo 用当前 baseline。你要是有时间可以并行调检索召回，不阻塞主线。
