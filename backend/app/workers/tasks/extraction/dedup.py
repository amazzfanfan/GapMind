"""Claim/limitation deduplication for knowledge extraction (P0 exact + P1 semantic).

During LLM extraction, the same evidence span can surface more than once:

  * the same fact is extracted twice across batch boundaries → two items
    with identical (type, span, content);
  * the same span is classified both as a claim and as a limitation (the
    LLM-as-a-Judge case in RG-1) → two items sharing a span but different
    types.

``dedup_exact`` collapses both cases before anything is written, and
returns the rejected items so the caller can record them as
``ExtractionRejection`` rows (auditable, never hard-deleted).

RG-1 also surfaced *near*-duplicates: the same fact extracted at two
*different* spans (e.g. "KG coverage 65.8%" twice as limitations). Those
need embedding similarity, which is ``dedup_semantic`` (P1, feature-flagged
behind ``retrieval_dedup_semantic``). It is deliberately conservative:

  * only items from the SAME paper (``source_provenance.paper_id``) are
    compared — across-paper items are never merged, even at high similarity;
  * only same-``type`` items are merged (a claim is never folded into a
    limitation);
  * similarity must reach ``SEMANTIC_DUP_THRESHOLD`` (0.90) — we'd rather
    keep two near-duplicates than silently merge two distinct facts.

Method/task/dataset items already carry a shared ``canonical_entity_id``
(see ``KnowledgeService.get_or_create_canonical_entity``); exact-span
duplicates of those are still worth dropping so the graph doesn't get two
nearly-identical mentions.

This module is deliberately side-effect free (pure functions over
``list[dict]``) so it can be unit-tested without a DB or LLM — same
pattern as ``extraction/batching.py`` / ``llm_caller.py``.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Callable

# Types that participate in cross-type same-span collision resolution.
# A method and a claim sharing a span are distinct facts; only claim vs
# limitation are treated as alternative classifications of one fact.
_DEDUP_CROSS_TYPES = frozenset({"claim", "limitation"})

# P1 semantic threshold. 0.9 is deliberately conservative: we'd rather keep
# two near-duplicates than silently merge two distinct facts.
SEMANTIC_DUP_THRESHOLD = 0.90


def content_signature(content: dict[str, Any] | None) -> str:
    """Stable signature of the substantive content text.

    Uses the claim statement / limitation description (the part that
    carries meaning) rather than the whole content dict, which may carry
    non-normalized extras (scope, conditions, severity).
    """
    content = content or {}
    text = str(content.get("statement") or content.get("description") or "")
    return hashlib.sha256(text.strip().casefold().encode("utf-8")).hexdigest()[:16]


def _span(item: dict[str, Any]) -> tuple[Any, ...] | None:
    """Normalized span key: ``(paper_id, start_char, end_char)``.

    The paper identity is part of the key so two items from *different*
    papers that coincidentally share the same ``(start_char, end_char)``
    are NOT treated as duplicates. ``artifact_id`` is used as a fallback
    when the item has no ``paper_id``.
    """
    sp = item.get("source_provenance") or {}
    start, end = sp.get("start_char"), sp.get("end_char")
    if start is None or end is None:
        return None
    paper_key = sp.get("paper_id") or sp.get("artifact_id") or ""
    return (str(paper_key), int(start), int(end))


def dedup_exact(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Collapse exact duplicates and same-span cross-type collisions.

    Returns ``(survivors, rejected)``.

    Rules:
      1. same ``(type, span, content_signature)`` → keep the first, reject
         the rest (applies to every type, including methods);
      2. same span, ``claim`` vs ``limitation`` → keep the higher-confidence
         item, reject the other.

    Items without a resolvable span are always kept (no signature to key on).
    """
    survivors: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    by_exact: dict[tuple[Any, ...], dict[str, Any]] = {}
    by_span: dict[tuple[Any, ...], dict[str, Any]] = {}

    for item in items:
        item_type = item.get("type")
        span = _span(item)
        sig = content_signature(item.get("content"))

        if span is None:
            # No span → can't key on it; keep.
            survivors.append(item)
            continue

        exact_key = (item_type, span, sig)

        # Rule 1: exact duplicate (same type, span, substantive content).
        if exact_key in by_exact:
            rejected.append(item)
            continue

        # Rule 2: same span, cross-type claim/limitation collision.
        if item_type in _DEDUP_CROSS_TYPES and span in by_span:
            prev = by_span[span]
            if prev.get("type") in _DEDUP_CROSS_TYPES and prev.get("type") != item_type:
                # Two alternative classifications of one fact → keep higher confidence.
                if item.get("confidence", 0.0) > prev.get("confidence", 0.0):
                    # Replace prev with item: drop prev's exact-key + span entries.
                    prev_sig = content_signature(prev.get("content"))
                    by_exact.pop((prev.get("type"), span, prev_sig), None)
                    survivors.remove(prev)
                    by_span[span] = item
                    rejected.append(prev)
                else:
                    rejected.append(item)
                    continue

        by_exact[exact_key] = item
        by_span.setdefault(span, item)
        survivors.append(item)

    return survivors, rejected


# ------------------------------------------------------------- P1: semantic near-dup

def semantic_text(content: dict[str, Any] | None) -> str:
    """The substantive text used for semantic comparison.

    Mirrors ``content_signature``: the claim statement / limitation
    description carries the meaning; scope/conditions/severity extras are
    ignored for similarity purposes.
    """
    content = content or {}
    return str(content.get("statement") or content.get("description") or "").strip()


def _paper_key(item: dict[str, Any]) -> str:
    """Paper identity for the same-paper guard (mirrors ``_span``)."""
    sp = item.get("source_provenance") or {}
    return str(sp.get("paper_id") or sp.get("artifact_id") or "")


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def dedup_semantic(
    items: list[dict[str, Any]],
    *,
    embed_texts: Callable[[list[str]], list[list[float]]],
    threshold: float = SEMANTIC_DUP_THRESHOLD,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """P1: collapse near-duplicate claims/limitations via embedding cosine.

    ``embed_texts(list[str]) -> list[vector]`` is injected so tests can stub
    it (the real caller batches via ``EmbeddingGateway.embed_texts``). Returns
    ``(survivors, rejected)``.

    Hard guards:
      * only same-``type`` items within the SAME paper are compared — a
        limitation is never folded into a claim, and two papers that merely
        sound alike are never merged;
      * similarity must be ``>= threshold`` (0.90 default).

    On a match the higher-confidence item survives; the other is returned as
    rejected so the caller can record an ``ExtractionRejection`` (nothing is
    hard-deleted). Items with no substantive text (or no type) are never
    deduped and are always kept.
    """
    if not items:
        return [], []

    texts = [semantic_text(item.get("content")) for item in items]
    indexable = [i for i, text in enumerate(texts) if text]

    vectors: list[list[float] | None] = [None] * len(items)
    if indexable:
        embedded = embed_texts([texts[i] for i in indexable])
        for j, idx in enumerate(indexable):
            vectors[idx] = embedded[j]

    # Group comparable items by (paper, type).
    groups: dict[tuple[str, str], list[tuple[int, list[float], dict[str, Any]]]] = {}
    for i, item in enumerate(items):
        item_type = item.get("type")
        if not item_type or not texts[i]:
            continue
        groups.setdefault(
            (_paper_key(item), str(item_type)), []
        ).append((i, vectors[i] or [], item))

    survivors: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    deduped_indices: set[int] = set()

    for (_paper, item_type), entries in groups.items():
        kept: list[tuple[int, list[float], dict[str, Any]]] = []
        for idx, emb, item in entries:
            deduped_indices.add(idx)
            dup = False
            for prev_idx, prev_emb, prev in kept:
                if _cosine(emb, prev_emb) >= threshold:
                    # Same-paper, same-type near-dup → keep higher confidence.
                    if item.get("confidence", 0.0) > prev.get("confidence", 0.0):
                        kept.remove((prev_idx, prev_emb, prev))
                        kept.append((idx, emb, item))
                        rejected.append(prev)
                    else:
                        rejected.append(item)
                    dup = True
                    break
            if not dup:
                kept.append((idx, emb, item))
        survivors.extend(item for _, _, item in kept)

    # Items outside any (paper, type) group are never deduped.
    survivors.extend(
        item for i, item in enumerate(items) if i not in deduped_indices
    )

    return survivors, rejected


__all__ = ["content_signature", "dedup_exact", "dedup_semantic", "semantic_text"]