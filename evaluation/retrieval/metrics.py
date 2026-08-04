"""Retrieval Gate metrics — pure functions, no I/O.

Each function takes plain data (sets/lists/floats) so the Gate math is
unit-testable without a DB, Milvus, or LLM.

Metric definitions (docs/phase3_smoke_validation_and_next_plan.md §6 V2):

  * Recall@K      — fraction of gold items present in the top-K results
  * MRR@K         — mean reciprocal rank of the first gold hit (0 if absent)
  * nDCG@K        — binary-relevance discounted cumulative gain
  * paper_diversity — distinct papers in top-K ÷ min(K, returned count)
  * workspace_leakage — fraction of returned items whose workspace_id does
                NOT match the queried workspace (must be 0)
"""

from __future__ import annotations

import math


def recall_at_k(gold: set[str], retrieved: list[str], k: int) -> float:
    """Fraction of gold items appearing in the first ``k`` retrieved IDs."""
    if not gold:
        return 0.0
    top_k = set(retrieved[:k])
    return len(gold & top_k) / len(gold)


def mrr_at_k(gold: set[str], retrieved: list[str], k: int) -> float:
    """Reciprocal rank of the first gold hit within top-k (0 if none)."""
    for rank, item in enumerate(retrieved[:k], start=1):
        if item in gold:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(gold: set[str], retrieved: list[str], k: int) -> float:
    """nDCG@K with binary relevance."""
    if not gold:
        return 0.0
    dcg = 0.0
    for i, item in enumerate(retrieved[:k]):
        if item in gold:
            dcg += 1.0 / math.log2(i + 2)
    ideal_count = min(len(gold), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))
    return dcg / idcg if idcg > 0 else 0.0


def paper_diversity(retrieved: list[str], k: int) -> float:
    """Fraction of distinct papers in top-k vs. the ideal max.

    ``1.0`` means every slot is a different paper; ``0.25`` means four
    hits all come from the same paper. Low diversity is what happens when
    a single paper's chunks dominate the top-k.
    """
    if not retrieved:
        return 0.0
    top_k = retrieved[:k]
    distinct = len(set(top_k))
    return distinct / min(k, len(top_k))


def workspace_leakage(workspace_ids: list[str], target_workspace_id: str) -> float:
    """Fraction of returned items belonging to a different workspace.

    For workspace-scoped retrieval this must be exactly 0.0; any positive
    value is a security/isolation defect, not a tuning knob.
    """
    if not workspace_ids:
        return 0.0
    leaked = sum(1 for wid in workspace_ids if wid != target_workspace_id)
    return leaked / len(workspace_ids)


def gate_report(
    *,
    recall: float,
    threshold: float,
    mrr: float | None = None,
    ndcg: float | None = None,
    diversity: float | None = None,
    leakage: float | None = None,
) -> dict[str, object]:
    """Build the per-benchmark Gate verdict block for the report JSON."""
    recall_passed = recall >= threshold - 1e-9
    return {
        "recall@10": round(recall, 4),
        "recall_threshold": threshold,
        "recall_passed": recall_passed,
        "mrr@10": round(mrr, 4) if mrr is not None else None,
        "ndcg@10": round(ndcg, 4) if ndcg is not None else None,
        "paper_diversity": round(diversity, 4) if diversity is not None else None,
        "workspace_leakage": round(leakage, 4) if leakage is not None else None,
        "passed": recall_passed and (leakage is None or leakage == 0.0),
    }


__all__ = [
    "recall_at_k",
    "mrr_at_k",
    "ndcg_at_k",
    "paper_diversity",
    "workspace_leakage",
    "gate_report",
]