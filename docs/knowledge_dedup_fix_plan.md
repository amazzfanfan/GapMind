# 知识抽取去重修复方案 + 实现草稿

> 更新日期：2026-08-04
> 来源：`docs/rg1_extraction_review_results.md`（RG-1 人工审查）+ 2026 年外部方案调研
> 目标：修复 claim/limitation 级的重复抽取，收敛知识图谱噪音

---

## 一、背景：RG-1 修正后的结论

RG-1 人工审查发现的问题，经查 `canonical_entity_id` 后修正：

| 现象 | 真相 | 结论 |
|---|---|---|
| PGIB × 2 method item | 共享 CE `25176e1d` | **同一实体 2 个 mention，符合设计** ✅ |
| GSAT 出现 2 个 CE | 分属不同 workspace | **workspace 隔离正确** ✅ |
| RAG × 3 / KG-GraphRAG × 2 | 同 workspace 共享 CE | **实体去重正常** ✅ |
| `LLM-as-a-Judge` span (7082,7323) 同时是 claim + limitation | 同 span 双类型 | 🔴 **真问题** |
| `KG coverage 65.8%` × 2 limitation | 不同 span 同一事实 | 🔴 **近重复** |
| `complementary strengths/behaviors` × 2 claim | 不同 span 同一结论 | 🔴 **近重复** |

**根因定位**：`_write_extraction` 的 `item_key = sha256(type | normalized_name | start_char | end_char)`。
- method/task/dataset 有 `get_or_create_canonical_entity`（按 normalization_key 去重）→ 实体层 OK
- claim/limitation **无实体级去重** → 同 span 双类型、近重复全靠 item_key 放行

---

## 二、外部方案调研（2026）

| 方案 | 出处 | 可借鉴点 |
|---|---|---|
| LLM 实体解析 + blocking + 硬护栏 | [Anthropic KG cookbook](https://platform.claude.com/cookbook/capabilities-knowledge-graph-guide) | 先 blocking 再 LLM 仲裁；一句话描述消歧 |
| 多信号 + 硬冲突护栏（zero false merge） | [arXiv 2607.28662](https://arxiv.org/html/2607.28662v1) | 任何相似度都不能覆盖护栏；recall 70%→95% |
| Claim 语义去重（embedding 余弦阈值） | [akashi #78](https://github.com/ashita-ai/akashi/issues/78) | 折叠高余弦相似 claim |
| 混合相似度 + 去重 Agent | [HSE multi-agent](https://www.hse.ru/en/edu/vkr/1160598263) | `sim = α·cos(BERT) + (1-α)·TSR` |
| LSH 全对近重复 | [LSHAlign (ACM)](https://dl.acm.org/doi/10.1145/3802083) | 大规模近重复 O(n²)→O(n) |
| 语义哈希去重 | [SemHash-LLM](https://arxiv-org.ezproxy.obspm.fr/html/2607.01601v1) | attention 降权样板文本，自适应阈值 |
| 去重分类学 | [Text Dedup Survey (IEEE)](https://www.semanticscholar.org/paper/A-Survey-of-Text-Deduplication%3A-From-Syntactic-to-Kim-Park/7827e3f98dc99fef79eb008daa6e37f449f12b8f) | exact / near / semantic 三类 |

**核心原则**：去重要保守——exact 去重零风险；near-dup 必须带硬冲突护栏（跨论文证据绝不合并，相似度阈值宁可漏不可误）。

---

## 三、分层修复方案

### P0 — 精确去重（零风险，先做）

**目标**：杀掉同 span 碰撞 + 同 span 双类型。

- `_write_extraction` 写入前，对 claim/limitation 做：
  1. **同 (type, span, content_signature)** → 丢弃重复
  2. **同 span + 不同类型**（claim vs limitation）→ 保留置信度高者，另一个记 rejection

### P1 — 语义近重复去重（akashi 式，评估后上）

**目标**：折叠"不同 span 同一事实"。

- 写入后对 claim/limitation 做 embedding 余弦相似度：
  - 阈值 **≥ 0.9**（保守）
  - **硬护栏**：只合并同 paper 内的近重复；跨 paper 不合并
  - 合并策略：保留高置信度 item，低置信度标 `superseded`（软删除 + 加 `equivalent_to` 关系），不物理删除

### P2 — Prompt 层收敛（治本）

**目标**：从源头减少噪音。

- `extract_v1.py` 三处：
  1. 不得从同一证据 span 同时产出 claim 和 limitation
  2. claim statement 必须完整句，不得从证据中段截取
  3. 不得添加证据中未出现的条件/数字/推测

### 为什么不上 LLM 仲裁（Anthropic 式）

多一次 LLM 调用 + 编排复杂度，MVP 阶段 ROI 低。观测到的重复都是高相似，embedding + 保守阈值够用。真要上时按 "blocking → LLM 仲裁 → 硬护栏" 补，不推翻现有结构。

---

## 四、实现草稿

### 4.1 新模块 `backend/app/workers/tasks/extraction/dedup.py`

```python
"""Claim/limitation deduplication for knowledge extraction (P0 + P1).

S7-style pure helpers: unit-testable without a DB, then wired into
``_write_extraction``. P0 (exact) is safe to merge now; P1 (semantic)
ships behind a conservative threshold + hard conflict guard.
"""

from __future__ import annotations

import hashlib
from typing import Any

# Hard guard: only merge near-duplicates WITHIN the same paper. Across-paper
# claims are never merged, even at high similarity — they may be two
# independent statements that merely sound alike.
MERGE_WITHIN_SAME_PAPER_ONLY = True

# P1 semantic threshold. 0.9 is deliberately conservative: we'd rather keep
# two near-duplicates than silently merge two distinct facts.
SEMANTIC_DUP_THRESHOLD = 0.90


def content_signature(content: dict[str, Any]) -> str:
    """Stable signature of the substantive content text for exact-dedup.

    Uses the claim statement / limitation description (the part that
    carries meaning), not the whole content dict (which may contain
    non-normalized extras like scope/conditions).
    """
    text = str(content.get("statement") or content.get("description") or "")
    return hashlib.sha256(text.strip().casefold().encode("utf-8")).hexdigest()[:16]


def dedup_exact(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """P0: drop exact duplicates and same-span cross-type collisions.

    Returns ``(survivors, rejected)`` where ``rejected`` are the items that
    should NOT be written (and SHOULD be recorded as ExtractionRejection).

    Rules:
      1. same (type, span, content_signature) → keep first, reject rest
      2. same span, claim vs limitation (cross-type) → keep higher confidence
    """
    survivors: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    # key -> surviving item
    by_exact: dict[tuple[Any, ...], dict[str, Any]] = {}
    by_span: dict[tuple[int, int], dict[str, Any]] = {}

    for item in items:
        item_type = item["type"]
        sp = item["source_provenance"]
        span = (sp["start_char"], sp["end_char"])
        sig = content_signature(item.get("content") or {})
        exact_key = (item_type, span, sig)

        # Rule 1: exact duplicate
        if exact_key in by_exact:
            rejected.append(item)
            continue

        # Rule 2: same span, cross-type (claim vs limitation)
        if item_type in {"claim", "limitation"} and span in by_span:
            prev = by_span[span]
            if prev["type"] in {"claim", "limitation"} and prev["type"] != item_type:
                # keep higher confidence
                if item.get("confidence", 0.0) > prev.get("confidence", 0.0):
                    rejected.append(prev)
                    survivors.remove(prev)
                    by_exact.pop((prev["type"], span, content_signature(prev.get("content") or {})), None)
                    by_span[span] = item
                    by_exact[exact_key] = item
                    survivors.append(item)
                else:
                    rejected.append(item)
                continue

        by_exact[exact_key] = item
        by_span.setdefault(span, item)
        survivors.append(item)

    return survivors, rejected


def dedup_semantic(
    items: list[dict[str, Any]],
    *,
    embed_fn: Any,
    threshold: float = SEMANTIC_DUP_THRESHOLD,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """P1: collapse near-duplicate claims/limitations via embedding cosine.

    ``embed_fn(text) -> list[float]`` is injected so tests can stub it.
    Hard guard: only merges items from the SAME paper (``paper_id``).

    The survivor list is returned; near-dups are rejected (recorded as
    rejections, not hard-deleted — a follow-up can promote them back if
    the merge was wrong).
    """
    survivors: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    # store (embedding, item) per paper for the similarity pass
    by_paper: dict[str, list[tuple[list[float], dict[str, Any]]]] = {}

    for item in items:
        pid = item.get("paper_id")
        text = str(item.get("content") or {}).get("statement") or str(item.get("content") or {}).get("description") or ""
        emb = embed_fn(text)
        by_paper.setdefault(pid, []).append((emb, item))

    for pid, entries in by_paper.items():
        kept: list[tuple[list[float], dict[str, Any]]] = []
        for emb, item in entries:
            dup = False
            for prev_emb, prev in kept:
                sim = _cosine(emb, prev_emb)
                if sim >= threshold and prev["type"] == item["type"]:
                    # same-paper near-dup → keep higher confidence
                    if item.get("confidence", 0.0) > prev.get("confidence", 0.0):
                        rejected.append(prev)
                        kept.remove((prev_emb, prev))
                        kept.append((emb, item))
                    else:
                        rejected.append(item)
                    dup = True
                    break
            if not dup:
                kept.append((emb, item))
        survivors.extend(item for _, item in kept)

    return survivors, rejected


def _cosine(a: list[float], b: list[float]) -> float:
    import math

    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
```

### 4.2 接入 `_write_extraction`（extract_knowledge.py）

```python
# inside _write_extraction, BEFORE the main write loop:
from app.workers.tasks.extraction.dedup import dedup_exact  # P0

items, rejected = dedup_exact(items)
# record rejected as ExtractionRejections so they're auditable (reuse _make_rejection)
for r in rejected:
    db.add(ks.create_rejection(_make_rejection(
        run=run, paper=paper,
        batch_index=r["source_provenance"].get("batch_index"),
        rejection_kind="item",
        stage="dedup_exact",
        reason_code="duplicate_item",
        reason_detail=f"Exact duplicate or same-span cross-type collision ({r['type']})",
        raw_payload=r,
        item_type=r["type"],
        canonical_name=r["canonical_name"],
        evidence_preview=str(r.get("evidence_text") or "")[:200],
    )))
# then proceed with the existing loop using the deduplicated `items`
```

### 4.3 P1 接入（可选，评估后）

```python
# in _run_extract, after _validate_and_rebase_evidence collects validated_items,
# before _write_extraction:
if settings.get("retrieval_dedup_semantic", False):  # feature-flagged
    from app.workers.tasks.extraction.dedup import dedup_semantic
    from app.gateway.embedding import get_embedding_gateway

    gw = get_embedding_gateway()
    validated_items, sem_rejected = dedup_semantic(
        validated_items, embed_fn=lambda t: gw.embed_one(t)
    )
    # record sem_rejected as rejections (stage="dedup_semantic")
```

### 4.4 P2 prompt 修改（extract_v1.py SYSTEM_PROMPT）

```text
原有 prompt 末尾追加三条硬约束：

- You MUST NOT extract the same evidence span as both a claim and a
  limitation; choose the single most fitting category.
- claim "statement" MUST be a complete sentence — never start mid-sentence
  or truncate the source clause.
- Do NOT add conditions, numbers, or claims that are not present in the
  evidence span. If the source says "on dataset X", keep "on dataset X";
  do not generalize to "always".
```

---

## 五、实施顺序与验收

| 步骤 | 改动 | 验收 |
|---|---|---|
| 1. P0 精确去重 | `extraction/dedup.py` + 接入 `_write_extraction` | 单元测试：同 span 双类型 → 只留 1；同 span 同 type → 只留 1 |
| 2. P2 prompt | `extract_v1.py` | 重跑一篇，claim/limitation 数量下降 |
| 3. 重跑三篇 | 全量重抽取 | `docs/rg1_extraction_review_results.md` 里标记的重复组收敛 |
| 4. P1 语义去重 | feature-flagged 接入 | 近重复（KG coverage ×2）合并；跨论文不误合并 |

**回滚**：P1 加 feature flag，关掉即回退。P0 是纯丢弃，重跑即恢复。

---

## 六、P0 实施状态（2026-08-05 已完成）

| 项 | 状态 |
|---|---|
| `extraction/dedup.py`（dedup_exact + content_signature） | ✅ 已实现 |
| 接入 `_write_extraction`（主循环前，被拒不硬删，记 ExtractionRejection） | ✅ 已接入 |
| `ExtractionRejectionCreate.stage` 加 `dedup_exact` | ✅ 已加 |
| 13 单测 + 2 集成测试 | ✅ 全过 |
| **关键修正**：span 键含 `paper_id` | 防止跨论文偶发相同 (start,end) 误合并 |

## 七、P0 静态验证结果（对旧 run 真实数据跑 dedup_exact）

> 背景：完整重抽取被 LLM 空输出 bug 阻塞（见 §八）。改为对**旧 run 已存在的真实 items** 静态跑 `dedup_exact`，验证 P0 在真实数据上去重正确。

| 论文 | 真实 items | 去重后 | 被拒 |
|---|---|---|---|
| PGIB | 24 | 24 | 0（本来就干净） |
| SunnyGNN | 17 | 14 | 3（**IMDB/ACM 同 span 数据集重复**，RG-1 未抓到的） |
| RAG vs GraphRAG | 62 | 61 | 1（**LLM-as-a-Judge 同 span 碰撞**，RG-1 主发现） |

**结论**：
- P0 精确去掉 RG-1 记录的 LLM-as-a-Judge limitation（同 span 7082-7323，claim 保留）
- 额外发现并去掉一组 RG-1 没看的数据集同 span 重复（SunnyGNN IMDB/ACM）
- **P0 在真实数据上正确工作，验收通过**

## 八、阻塞：LLM 空输出生产 bug（与 P0 无关，上游问题）

### 现象
`verify_dedup.py` 触发真实重抽取时，Deepseek 返回空 content，3 次重试全失败。

### 根因（实测）
```
finish_reason: length
completion=16384（全部被 reasoning 吃掉）
content len: 0
reasoning_content: 65431 字符
```
`deepseek-v4-flash` 是 reasoning 模型，对 5706-token 的输入就产生 65431 字符 CoT，**烧光 16384 max_tokens → content 空**。与 `phase3_smoke_validation_and_next_plan.md` §3.6 记录的 Judge 空输出同类。

### 修复方向（Deepseek thinking mode 文档）
- OpenAI 兼容 API 关闭思考：`extra_body={"thinking": {"type": "disabled"}}`
- **不能同时传 `reasoning_effort`**（`thinking.type="disabled"` + `reasoning_effort` → 400 冲突）
- `enable_thinking: false` 是 SiliconFlow 等第三方格式，官方 OpenAI 兼容路径用 `thinking.type`

### 影响范围
- `extract_knowledge` 提取：对整篇论文 batch 必现
- `judge`（已有 §3.6 处理）：当时靠加 token 预算缓解
- 建议：在 `app/gateway/llm.py` 的 `chat_completion` 加 `thinking={"type":"disabled"}` 参数（或按模型区分），并测试小批量确认不再空输出

## 状态更新记录

| 日期 | 内容 |
|---|---|
| 2026-08-05 | P0 实现完成 + 静态验证通过；发现 LLM 空输出生产 bug，记录 thinking mode 修复方向 |
