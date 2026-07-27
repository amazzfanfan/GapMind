"""Retrieval evaluation script.

Runs eval_queries.json against the retrieval service and computes metrics.
Compares: baseline (vector only) vs reranked vs judged.

Usage:
    cd backend
    python -m evaluation.retrieval.run_eval --workspace-id <wid> [--minimal]

Or directly:
    cd GapMind
    python evaluation/retrieval/run_eval.py --workspace-id <wid> [--minimal]

Metrics:
  - Recall@K: fraction of expected papers found in top-K results
  - MRR: Mean Reciprocal Rank of first relevant result
  - nDCG@K: normalized Discounted Cumulative Gain
  - Judgement accuracy (counter_evidence only)

The --minimal flag reduces API calls (top_k=5, skip judge) for cost control.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

# Ensure backend is importable
BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.domains.retrieval.service import (  # noqa: E402
    find_counter_evidence,
    find_similar_work,
    semantic_search,
)


def load_queries(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------
# Metrics
# ------------------------------------------------------------------


def recall_at_k(results: list[dict], expected_paper_ids: list[str], k: int) -> float:
    """Fraction of expected papers found in top-K results."""
    if not expected_paper_ids:
        return -1.0  # not applicable
    found = set()
    for item in results[:k]:
        pid = item.get("paper_id")
        if pid in expected_paper_ids:
            found.add(pid)
    return len(found) / len(expected_paper_ids)


def mrr(results: list[dict], expected_paper_ids: list[str]) -> float:
    """Mean Reciprocal Rank of first relevant result."""
    if not expected_paper_ids:
        return -1.0
    for i, item in enumerate(results):
        if item.get("paper_id") in expected_paper_ids:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(results: list[dict], expected_paper_ids: list[str], k: int) -> float:
    """nDCG@K with binary relevance."""
    if not expected_paper_ids:
        return -1.0
    dcg = 0.0
    for i, item in enumerate(results[:k]):
        if item.get("paper_id") in expected_paper_ids:
            dcg += 1.0 / math.log2(i + 2)
    # Ideal DCG: all relevant at top
    ideal_count = min(len(expected_paper_ids), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))
    return dcg / idcg if idcg > 0 else 0.0


# ------------------------------------------------------------------
# Runner
# ------------------------------------------------------------------


def run_eval(
    queries: list[dict],
    workspace_id: str,
    *,
    minimal: bool = False,
    top_k: int = 10,
) -> dict:
    """Run all queries and collect metrics."""
    if minimal:
        top_k = 5

    report = {
        "workspace_id": workspace_id,
        "minimal_mode": minimal,
        "top_k": top_k,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": [],
        "summary": {},
    }

    metrics_accum = {"recall": [], "mrr": [], "ndcg": [], "judgement_correct": [], "latency": []}

    for q in queries:
        qtype = q["type"]
        wid = workspace_id  # override from CLI

        print(f"  [{q['id']}] {qtype}: {q.get('query', q.get('paper_id', ''))[:60]}...")

        if qtype == "semantic_search":
            # Baseline (no reranker)
            resp_base = semantic_search(wid, q["query"], top_k=top_k, use_reranker=False)
            # With reranker
            resp_rerank = semantic_search(wid, q["query"], top_k=top_k, use_reranker=True)

            base_items = [i.model_dump() for i in resp_base.items]
            rerank_items = [i.model_dump() for i in resp_rerank.items]

            expected = q.get("expected_paper_ids", [])
            entry = {
                "id": q["id"],
                "type": qtype,
                "query": q["query"],
                "baseline": {
                    "recall": recall_at_k(base_items, expected, top_k),
                    "mrr": mrr(base_items, expected),
                    "ndcg": ndcg_at_k(base_items, expected, top_k),
                    "latency_ms": resp_base.latency_ms,
                    "count": len(base_items),
                },
                "reranked": {
                    "recall": recall_at_k(rerank_items, expected, top_k),
                    "mrr": mrr(rerank_items, expected),
                    "ndcg": ndcg_at_k(rerank_items, expected, top_k),
                    "latency_ms": resp_rerank.latency_ms,
                    "count": len(rerank_items),
                },
            }
            # Accumulate reranked metrics
            if expected:
                metrics_accum["recall"].append(entry["reranked"]["recall"])
                metrics_accum["mrr"].append(entry["reranked"]["mrr"])
                metrics_accum["ndcg"].append(entry["reranked"]["ndcg"])
            metrics_accum["latency"].append(resp_rerank.latency_ms)

        elif qtype == "counter_evidence":
            # With reranker + judge (skip judge in minimal mode)
            use_judge = not minimal
            resp = find_counter_evidence(
                wid, q["query"], top_k=top_k, use_reranker=True, use_judge=use_judge
            )
            items = [i.model_dump() for i in resp.items]

            expected_judgements = set(q.get("expected_judgement", []))
            judgement_correct = 0
            judgement_total = 0
            for item in items:
                if item["judgement"] != "unknown":
                    judgement_total += 1
                    if item["judgement"] in expected_judgements:
                        judgement_correct += 1

            entry = {
                "id": q["id"],
                "type": qtype,
                "query": q["query"],
                "status": resp.status,
                "latency_ms": resp.latency_ms,
                "count": len(items),
                "judgements": [i["judgement"] for i in items],
                "judgement_accuracy": judgement_correct / judgement_total if judgement_total > 0 else -1.0,
            }
            if judgement_total > 0:
                metrics_accum["judgement_correct"].append(
                    judgement_correct / judgement_total
                )
            metrics_accum["latency"].append(resp.latency_ms)

        elif qtype == "similar_work":
            paper_id = q.get("query", "").replace("paper:", "")
            if not paper_id or paper_id == "FILL_PAPER_ID":
                print(f"    SKIP (no paper_id)")
                continue
            resp = find_similar_work(wid, paper_id, top_k=top_k, use_reranker=True)
            items = [i.model_dump() for i in resp.items]

            expected = q.get("expected_paper_ids", [])
            entry = {
                "id": q["id"],
                "type": qtype,
                "paper_id": paper_id,
                "recall": recall_at_k(items, expected, top_k),
                "latency_ms": resp.latency_ms,
                "count": len(items),
            }
            metrics_accum["latency"].append(resp.latency_ms)

        else:
            continue

        report["results"].append(entry)

    # Summary
    def safe_avg(lst):
        valid = [x for x in lst if x >= 0]
        return round(sum(valid) / len(valid), 4) if valid else None

    report["summary"] = {
        "avg_recall_at_k": safe_avg(metrics_accum["recall"]),
        "avg_mrr": safe_avg(metrics_accum["mrr"]),
        "avg_ndcg_at_k": safe_avg(metrics_accum["ndcg"]),
        "avg_judgement_accuracy": safe_avg(metrics_accum["judgement_correct"]),
        "avg_latency_ms": safe_avg(metrics_accum["latency"]),
        "total_queries": len(report["results"]),
    }

    return report


def main():
    parser = argparse.ArgumentParser(description="GapMind Retrieval Evaluation")
    parser.add_argument("--workspace-id", required=True, help="Workspace ID to evaluate")
    parser.add_argument("--minimal", action="store_true", help="Reduce API calls (top_k=5, skip judge)")
    parser.add_argument("--top-k", type=int, default=10, help="Top K results")
    parser.add_argument("--queries", type=str, default=None, help="Path to eval_queries.json")
    parser.add_argument("--output", type=str, default=None, help="Output report path")
    args = parser.parse_args()

    queries_path = Path(args.queries) if args.queries else Path(__file__).parent / "eval_queries.json"
    queries = load_queries(queries_path)

    print(f"=== GapMind Retrieval Evaluation ===")
    print(f"Workspace: {args.workspace_id}")
    print(f"Queries: {len(queries)} | Minimal: {args.minimal} | Top-K: {args.top_k}")
    print()

    report = run_eval(queries, args.workspace_id, minimal=args.minimal, top_k=args.top_k)

    # Print summary
    print("\n=== Summary ===")
    for k, v in report["summary"].items():
        print(f"  {k}: {v}")

    # Save report
    output_path = Path(args.output) if args.output else Path(__file__).parent / "eval_report.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nReport saved to: {output_path}")


if __name__ == "__main__":
    main()
