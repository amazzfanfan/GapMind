"""Stage 3 external novelty Gate runner.

Loads an external gold set, runs the *real* external-search path
(``DiscoverService._build_external_queries`` + ``_external_verify``) against a
live workspace, and checks whether each gold external paper is recalled within
the top-K merged candidates.

Gate criterion (mirrors Stage-2 thresholds):

    gold external counter/overlap/qualify papers in top-K merged candidates
    Recall@K >= threshold (default 0.8, K default 10)

The runner uses the production ``DiscoverService`` with the real
``SemanticScholarClient`` adapter, so it exercises the same multi-query merge,
dedupe-by-external-paper-id, and rank assignment the Discover Agent uses. The
LLM role-judge is stubbed (roles stay heuristic) because the Gate criterion is
*recall of the candidate* — role refinement only rewrites the role field.

A verification ``DiscoverRun`` is persisted (trigger_type="verification") so
the surfaced candidates are auditable in the demo workspace; pass ``--cleanup``
to delete the run + candidates after reporting.

Usage (run from ``backend/`` so ``.env`` is loaded — mirrors run_eval.py):

    python ..\\evaluation\\external\\verify_external_gate.py \\
        --workspace-id <uuid> \\
        --gold evaluation/external/gold/demo_sig_ood_external_v1.json \\
        [--top-k 10] [--research-question "..."] [--keywords a,b,c] \\
        [--cleanup] [--output evaluation/external/reports/demo_v1.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

# --- sys.path: allow running from repo root OR backend/ without `-m` ---
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
for p in (str(BACKEND_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from evaluation.retrieval.metrics import (  # noqa: E402
    gate_report,
    mrr_at_k,
    recall_at_k,
)
from sqlalchemy import select  # noqa: E402

import app.db.models  # noqa: E402,F401  (register all models)
from app.db.session import SessionLocal  # noqa: E402
from app.domains.discover.models import (  # noqa: E402
    DiscoverExternalCandidate,
    DiscoverRun,
)
from app.domains.discover.service import DiscoverService  # noqa: E402


class _NoopLLM:
    """Stub LLM — role refinement is irrelevant to candidate recall."""

    def chat_completion(self, messages, **kwargs):
        return SimpleNamespace(content=json.dumps({"roles": []}))


def load_gold(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _run(db, gold: dict[str, Any], workspace_id: str, args: argparse.Namespace) -> int:
    research_question = (args.research_question or gold["research_question"]).strip()
    keywords = [k.strip() for k in (args.keywords or "").split(",") if k.strip()] or gold.get("default_keywords", [])
    top_k = args.top_k
    threshold = args.threshold if args.threshold is not None else gold["gate"]["threshold"]
    gold_papers = gold["gold_papers"]
    gold_ids = {p["semantic_scholar_id"] for p in gold_papers}

    print("=== Stage 3 External Novelty Gate ===")
    print(f"Case: {gold.get('case_id')} | v{gold.get('version')} | annotation: {gold.get('annotation_status')}")
    print(f"Workspace: {workspace_id} | Top-K: {top_k} | Threshold: {threshold} | Gold papers: {len(gold_papers)}")
    print(f"Research question: {research_question}")

    # A verification DiscoverRun is persisted so candidates are auditable.
    run = DiscoverRun(
        workspace_id=workspace_id,
        trigger_type="verification",
        input_topic=research_question,
        input_payload={"topic": research_question, "keywords": keywords},
        scope={},
        config={"top_k": top_k},
        status="running",
        stage="external_search",
        progress=0.5,
        verification_status="in_progress",
        stage_summaries={},
    )
    db.add(run)
    db.commit()

    service = DiscoverService(db, llm=_NoopLLM())
    if args.queries:
        # Pipeline-only verification: bypass query generation so the Gate can
        # isolate retrieval/merge/role defects from query-construction defects.
        queries = [q.strip() for q in args.queries.split(",") if q.strip()]
    else:
        queries = service._build_external_queries(run, research_question)
    count = service._external_verify(run, queries)
    run_summary = dict(run.stage_summaries or {}).get("external_search", {})
    if run_summary.get("status") == "failed":
        print(f"\n[ERROR] external search failed: {run_summary.get('error')}")
        return 2

    print(f"\nqueries used ({len(queries)}):")
    for q in queries:
        print(f"  - {q[:110]}")
    print(f"external candidates merged: {count}")

    candidates = list(
        db.execute(
            select(DiscoverExternalCandidate)
            .where(DiscoverExternalCandidate.discover_run_id == run.id)
            .order_by(DiscoverExternalCandidate.rank)
        ).scalars()
    )
    candidate_ids = [c.external_paper_id for c in candidates]
    candidate_by_id = {c.external_paper_id: c for c in candidates}

    per_paper: list[dict[str, Any]] = []
    for p in gold_papers:
        pid = p["semantic_scholar_id"]
        cand = candidate_by_id.get(pid)
        per_paper.append(
            {
                "title": p["title"],
                "semantic_scholar_id": pid,
                "year": p.get("year"),
                "expected_role": p.get("expected_role"),
                "recalled": cand is not None,
                "rank": cand.rank if cand else None,
                "rank_in_top_k": bool(cand and cand.rank <= top_k),
                "source_query": cand.query if cand else None,
                "assigned_role": cand.role if cand else None,
            }
        )

    recall = recall_at_k(gold_ids, candidate_ids, top_k)
    mrr = mrr_at_k(gold_ids, candidate_ids, top_k)

    # Which queries actually surfaced gold papers (diagnostic).
    gold_by_query: dict[str, list[str]] = {}
    for entry in per_paper:
        if entry["recalled"] and entry["source_query"]:
            gold_by_query.setdefault(entry["source_query"][:80], []).append(entry["title"])

    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "case_id": gold.get("case_id"),
        "version": gold.get("version"),
        "annotation_status": gold.get("annotation_status"),
        "workspace_id": workspace_id,
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "research_question": research_question,
        "top_k": top_k,
        "threshold": threshold,
        "query_source": "explicit" if args.queries else "auto",
        "queries": queries,
        "external_search_summary": run_summary,
        "gate": gate_report(recall=recall, threshold=threshold, mrr=mrr),
        "gate_passed": recall >= threshold - 1e-9,
        "per_paper": per_paper,
        "recall_by_source_query": gold_by_query,
        "candidate_count": count,
    }

    print("\n=== Gate verdict ===")
    for entry in per_paper:
        mark = "HIT " if entry["rank_in_top_k"] else ("miss" if entry["recalled"] else "NONE")
        print(f"  [{mark}] rank={entry['rank']} {entry['expected_role']:>9} {entry['title'][:70]}")
    status = "PASS" if report["gate_passed"] else "FAIL"
    print(f"  recall@{top_k}={recall:.3f} (threshold {threshold}) mrr@{top_k}={mrr:.3f}")
    print(f"  overall: {status}")

    output_path = Path(args.output) if args.output else (
        Path(__file__).parent / "reports" / f"{gold.get('case_id')}_external_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport saved to: {output_path}")
    print(f"Run id: {run.id} (trigger_type=verification)")

    if args.cleanup:
        db.execute(
            DiscoverExternalCandidate.__table__.delete().where(
                DiscoverExternalCandidate.discover_run_id == run.id
            )
        )
        db.delete(run)
        db.commit()
        print("Cleanup: verification run + candidates deleted.")

    return 0 if report["gate_passed"] else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=False, help="Local workspace UUID (overrides gold workspace_hint).")
    parser.add_argument("--gold", type=str, required=True, help="Path to the external gold-set JSON file.")
    parser.add_argument("--top-k", type=int, default=10, help="Top-K for the Gate (default 10).")
    parser.add_argument("--threshold", type=float, default=None, help="Recall threshold (default: gold set gate.threshold).")
    parser.add_argument("--research-question", type=str, default=None, help="Primary query override (default: gold research_question).")
    parser.add_argument("--keywords", type=str, default=None, help="Comma-separated input keywords (default: gold default_keywords).")
    parser.add_argument("--queries", type=str, default=None, help="Comma-separated explicit query list; bypasses _build_external_queries (pipeline-only verification).")
    parser.add_argument("--cleanup", action="store_true", help="Delete the verification run + candidates after reporting.")
    parser.add_argument("--output", type=str, default=None, help="Report output path (default: reports/<case_id>_external_<ts>.json).")
    args = parser.parse_args()

    gold_path = Path(args.gold)
    if not gold_path.exists():
        print(f"Gold set not found: {gold_path}")
        return 1
    gold = load_gold(gold_path)

    workspace_id = args.workspace_id or gold.get("workspace_hint")
    if not workspace_id:
        print("No workspace_id. Pass --workspace-id or set workspace_hint in the gold set.")
        return 1

    db = SessionLocal()
    try:
        return _run(db, gold, workspace_id, args)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
