# 0811 版本冻结清单（W6-1）

> 日期：2026-08-11
> 作者：yx
> 状态：清单已整理，**正式冻结（W6-2 三次端到端通过后）待确认**
> 关联：`research_assistant_completion_plan.md` W6 封版；`0809_delivery.md` 交付说明

---

## 一、冻结目标

演示/交付的可复现基准：**同一语料、同一标注、同一 Prompt、同一模型、同一解析器、同一 Schema 下，3 次全新数据库端到端跑通**。本清单记录当前版本快照；任何改动须升版本并同步本文档。

## 二、版本清单

### 1. 语料（corpus）

| 项 | 版本/内容 |
|---|---|
| Demo 工作区语料 | 18 篇论文（GNNExplainer / PGExplainer / PGM-Explainer / SubgraphX / GraphFramEx / Zorro / GOOD / OOD-GNN / GSAT / DIR / SunnyGNN / RAG 等），来源 S2 导入 + arXiv PDF |
| PDF 来源 | Semantic Scholar openAccessPdf + arXiv 直链 |
| 解析产出 | chunk 文本（PyMuPDF 解析，NUL 已剥离）|

### 2. 标注 / Gold Set（评测基准，固定不随产品改动）

| 项 | 文件 |
|---|---|
| 检索 Gold Set | `evaluation/retrieval/gold/demo_sig_ood_v1.json`（starter）+ `counter_evidence_v4.json`（15 条反证主张）|
| 外部核验 Gold Set | `evaluation/external/gold/demo_sig_ood_external_v1.json`（7 篇 corpus 外真实论文：GIB/IRM/GREA/Fragile/Sanity/Reliable/…）|
| 抽取回链审查 | `rg1_extraction_review*.md`（103 spans 精确回链）|

> 规则：Gold Set 是固定基准，**不得为过评测而改**（区别于产品相关性评测）。

### 3. Prompt 版本

| Prompt | 位置 | 版本 |
|---|---|---|
| Discover 编排 | `DISCOVER_PROMPT_VERSION`（service.py）| `discover-v2` |
| CriticAgent | `CRITIC_SYSTEM_PROMPT`（critic.py）| 随 MA-1 落位 |
| 外部轴 query | `EXTERNAL_QUERY_AXIS_SYSTEM_PROMPT`（external_retrieval.py）| 随 MA-1 落位 |
| 外部角色判别（metadata）| `EXTERNAL_ROLE_SYSTEM_PROMPT` | 随 MA-1 落位 |
| 外部角色重判（全文）| `EXTERNAL_FULLTEXT_ROLE_SYSTEM_PROMPT` | W1 新增 |
| 机会综合 | `SYNTHESIS_SYSTEM_PROMPT`（synthesis.py）| 随 MA-1 落位 |
| 知识抽取 | extract_v1（extract_knowledge）| 基线 |

### 4. 模型

| 角色 | 模型 | 说明 |
|---|---|---|
| 主 LLM | `deepseek-v4-flash` | 一律 `disable_thinking=True`，勿同时传 `reasoning_effort` |
| Gap Board 微调 | `research-dataset-qwen3`（服务器 Ollama，SSH 隧道 127.0.0.1:11434）| zf 微调，本机勿装本地 Ollama |
| 向量 | 硅基流动 **BGE-m3**（1024 维）| Milvus 索引 |
| 重排 | 硅基流动 **BGE-reranker-v2-m3** | 检索 rerank |

### 5. 解析器

| 项 | 版本 |
|---|---|
| PDF 解析 | PyMuPDF (fitz)，**标题字号阈值 ≥11.5**（SubgraphX 11.95pt 可识别；<12.0 旧阈值误拒）|
| NUL 防护 | 剥离 `\x00`，检索文本拼 SQL 前 `replace("\x00","")` |

### 6. Schema / 迁移

| 项 | 版本 |
|---|---|
| Alembic head | `0015_gap_board`（agent 表 0014 + gap 表 0015）|
| 业务表 | ~20 张（workspaces/papers/knowledge/discover/opportunity/agent/chat/gap_*）|
| 软删除 | 全表软删除（`is_deleted` / `discover_runs.deleted_at`）|

### 7. 技术栈 / 测试基线

| 项 | 版本 |
|---|---|
| 后端 | FastAPI + Python 3.11，**363 测试全过** |
| 前端 | React 18 + TS + Vite + antd 5，tsc 通过 + 26 vitest |
| 类型生成 | `api.gen.ts` 由 OpenAPI 自动生成（`npm run gen:api`），勿手写 |
| 代码结构 | Discover 已拆分：`critic.py` / `synthesis.py` / `external_retrieval.py` / `utils.py`，service.py 1340 行 |

## 三、待环境确认项（W6-2/3）

- [ ] **W6-2**：3 次全新数据库端到端演练（导入→解析→抽取→检索→Discover→HITL→计划→代码→分析/写作/回复）
- [ ] **W6-3**：记录解析/抽取/检索/发现的耗时、错误率、token 成本
- [ ] **W6-4**：演示脚本打磨（agent 交接 + 证据回链 + 可信度卡片）

## 四、冻结后改动流程

1. 任何语料/Prompt/模型/解析器/Schema 变更 → 升版本号（如 `discover-v2`→`discover-v3`）并更新本文档
2. 重新跑 W6-2 三次端到端确认
3. 评测 Gold Set 固定不变
