"""Retrieval Gate evaluation runner.

Loads a GoldSet (see ``gold_set.py``), runs the three retrieval functions
against a live workspace, and produces a JSON report that answers the
Stage-2 Gate question (docs/phase3_smoke_validation_and_next_plan.md §6 V2):

    Semantic Search    Recall@10 ≥ 0.80
    Similar Work       Recall@10 ≥ 0.80
    Counter Evidence   Recall@10 ≥ 0.70
    workspace leakage  = 0
    every result traceable to a Paper + artifact

Usage:

    # repo root (script inserts backend + evaluation onto sys.path itself)
    python evaluation/retrieval/run_eval.py \
        --workspace-id <uuid> \
        --gold evaluation/retrieval/gold/demo_sig_ood_v1.json \
        [--minimal] [--top-k 10] [--output evaluation/retrieval/reports/demo_v1.json]

``--minimal`` skips the LLM judge (cheap smoke; the real Gate must run the
judge so counter-evidence roles are meaningful).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# --- sys.path: allow running from repo root OR backend/ without `-m` ---
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
for p in (str(BACKEND_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import select  # noqa: E402

import app.db.models  # noqa: E402,F401  (register all models)
from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.domains.paper.models import Paper  # noqa: E402
from app.domains.retrieval.service import (  # noqa: E402
    find_counter_evidence,
    find_similar_work,
    semantic_search,
)
from evaluation.retrieval.gold_set import (  # noqa: E402
    CounterEvidenceQuery,
    GoldSet,
    SemanticSearchQuery,
    SimilarWorkQuery,
)
from evaluation.retrieval.metrics import (  # noqa: E402
    gate_report,
    mrr_at_k,
    ndcg_at_k,
    paper_diversity,
    recall_at_k,
    workspace_leakage,
)

# Stage-2 Gate thresholds (docs/phase3_smoke_validation_and_next_plan.md §6 V2).
GATE_THRESHOLDS = {
    "semantic_search": 0.80,
    "similar_work": 0.80,
    "counter_evidence": 0.70,
}


# ------------------------------------------------------------ paper refs
def resolve_paper_ref(db, workspace_id: str, paper_ref: str) -> Paper | None:
    """Resolve a portable paper reference to a local Paper row.

    Precedence:
      1. exact local UUID match (``Paper.id``)
      2. Semantic Scholar external ID match (``Paper.external_paper_id``)
      3. title match (case-insensitive exact, then prefix)
    All matches are workspace-scoped — a ref that exists in another
    workspace is treated as unresolved (safer than leaking across scopes).
    """
    ref = paper_ref.strip()
    if not ref:
        return None

    base = select(Paper).where(
        Paper.workspace_id == workspace_id,
        Paper.is_deleted.is_(False),
    )

    # 1. UUID
    paper = db.execute(base.where(Paper.id == ref)).scalars().first()
    if paper is not None:
        return paper

    # 2. external ID
    paper = db.execute(
        base.where(Paper.external_paper_id == ref)
    ).scalars().first()
    if paper is not None:
        return paper

    # 3. title (case-insensitive exact, then prefix)
    lowered = ref.lower()
    for candidate in db.execute(base).scalars().all():
        title = (candidate.title or "").strip()
        if title.lower() == lowered:
            return candidate
    for candidate in db.execute(base).scalars().all():
        title = (candidate.title or "").strip()
        if title.lower().startswith(lowered):
            return candidate
    return None


def resolve_many(db, workspace_id: str, refs: list[str]) -> dict[str, str | None]:
    """Map each paper_ref → local UUID (or ``None`` if unresolved)."""
    resolved: dict[str, str | None] = {}
    for ref in refs:
        paper = resolve_paper_ref(db, workspace_id, ref)
        resolved[ref] = paper.id if paper is not None else None
    return resolved


# ------------------------------------------------------------ per-query
def _paper_ids(items: list[Any]) -> list[str]:
    """Unique, ordered paper_ids from RetrievalResultItems."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        pid = getattr(item, "paper_id", None)
        if pid and pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out


def _paper_workspace_ids(db, items: list[Any], target_workspace_id: str) -> list[str]:
    """Workspace id of each retrieved item, resolved via the DB.

    ``RetrievalResultItem`` carries ``paper_id`` but NOT ``workspace_id``
    (workspace scoping happens inside the Milvus filter). To compute real
    leakage we look each paper up; unknown / None paper_ids count as in-scope
    (they cannot have crossed the workspace boundary by construction).
    """
    paper_ids = [getattr(item, "paper_id", None) for item in items]
    present = [pid for pid in paper_ids if pid]
    wmap: dict[str, str] = {}
    if present:
        for row in db.query(Paper).filter(Paper.id.in_(present)).all():
            wmap[row.id] = row.workspace_id
    return [wmap.get(pid, target_workspace_id) if pid else target_workspace_id for pid in paper_ids]


def run_semantic_search(db, workspace_id: str, q: SemanticSearchQuery, top_k: int, minimal: bool):
    target = resolve_paper_ref(db, workspace_id, q.target_paper_ref)
    if target is None:
        return {"query_id": q.query_id, "error": f"unresolved target_paper_ref: {q.target_paper_ref}"}

    resp = semantic_search(workspace_id, q.query, top_k=top_k, use_reranker=not minimal)
    pids = _paper_ids(resp.items)
    return {
        "query_id": q.query_id,
        "query": q.query,
        "target_paper_id": target.id,
        "retrieved_paper_ids": pids,
        "status": resp.status,
        "count": len(pids),
        "recall@10": recall_at_k({target.id}, pids, top_k),
        "mrr@10": mrr_at_k({target.id}, pids, top_k),
        "leakage": workspace_leakage(_paper_workspace_ids(db, resp.items, workspace_id), workspace_id),
    }


def run_similar_work(db, workspace_id: str, q: SimilarWorkQuery, top_k: int, minimal: bool):
    source = resolve_paper_ref(db, workspace_id, q.source_paper_ref)
    if source is None:
        return {"query_id": q.query_id, "error": f"unresolved source_paper_ref: {q.source_paper_ref}"}
    resolved_gold = resolve_many(db, workspace_id, q.relevant_paper_refs)
    gold_ids = {pid for pid in resolved_gold.values() if pid}
    if not gold_ids:
        return {"query_id": q.query_id, "error": "no gold relevant papers resolved"}

    resp = find_similar_work(
        workspace_id,
        source.id,
        top_k=top_k,
        use_reranker=not minimal,
        exclude_paper_ids={source.id},
    )
    pids = _paper_ids(resp.items)
    return {
        "query_id": q.query_id,
        "source_paper_id": source.id,
        "gold_paper_ids": sorted(gold_ids),
        "retrieved_paper_ids": pids,
        "status": resp.status,
        "count": len(pids),
        "recall@10": recall_at_k(gold_ids, pids, top_k),
        "mrr@10": mrr_at_k(gold_ids, pids, top_k),
        "diversity": paper_diversity(pids, top_k),
        "leakage": workspace_leakage(_paper_workspace_ids(db, resp.items, workspace_id), workspace_id),
        "source_leaked": source.id in pids,
    }


def run_counter_evidence(db, workspace_id: str, q: CounterEvidenceQuery, top_k: int, minimal: bool):
    source = resolve_paper_ref(db, workspace_id, q.source_paper_ref)
    if source is None:
        return {"query_id": q.query_id, "error": f"unresolved source_paper_ref: {q.source_paper_ref}"}
    resolved_gold = resolve_many(db, workspace_id, [r.paper_ref for r in q.gold_roles])
    gold_ids = {pid for pid in resolved_gold.values() if pid}
    if not gold_ids:
        return {"query_id": q.query_id, "error": "no gold counter-evidence papers resolved"}

    resp = find_counter_evidence(
        workspace_id,
        q.claim_text,
        top_k=top_k,
        use_reranker=True,
        use_judge=not minimal,
        exclude_paper_ids={source.id},
    )
    pids = _paper_ids(resp.items)
    # Role-correct recall is diagnostic only (Stage-2 threshold is on paper recall).
    role_paper_ids = {pid for ref, pid in resolved_gold.items() if pid}
    roles_by_paper: dict[str, str] = {
        resolved_gold[r.paper_ref]: r.role
        for r in q.gold_roles
        if resolved_gold.get(r.paper_ref)
    }
    role_correct = sum(
        1 for pid in pids[:top_k] if roles_by_paper.get(pid) == "contradicts"
    ) + 0.5 * sum(
        1 for pid in pids[:top_k] if roles_by_paper.get(pid) == "qualifies"
    )
    role_recall = role_correct / len(gold_ids) if gold_ids else 0.0

    return {
        "query_id": q.query_id,
        "source_paper_id": source.id,
        "gold_paper_ids": sorted(gold_ids),
        "retrieved_paper_ids": pids,
        "status": resp.status,
        "count": len(pids),
        "recall@10": recall_at_k(gold_ids, pids, top_k),
        "mrr@10": mrr_at_k(gold_ids, pids, top_k),
        "diversity": paper_diversity(pids, top_k),
        "leakage": workspace_leakage(_paper_workspace_ids(db, resp.items, workspace_id), workspace_id),
        "source_leaked": source.id in pids,
        "role_recall_diagnostic": round(role_recall, 4),
    }


# ------------------------------------------------------------ aggregation
def _aggregate(entries: list[dict], keys: tuple[str, ...]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for key in keys:
        vals = [e[key] for e in entries if key in e and isinstance(e[key], (int, float))]
        out[key] = round(sum(vals) / len(vals), 4) if vals else None
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=False, help="Local workspace UUID (overrides gold set hint).")
    parser.add_argument("--gold", type=str, required=True, help="Path to the gold-set JSON file.")
    parser.add_argument("--minimal", action="store_true", help="Skip LLM judge (cheap smoke; real Gate must run judge).")
    parser.add_argument("--top-k", type=int, default=10, help="Top-K for the Gate (default 10).")
    parser.add_argument("--output", type=str, default=None, help="Report output path (default: reports/<case_id>_<ts>.json).")
    args = parser.parse_args()

    gold_path = Path(args.gold)
    if not gold_path.exists():
        print(f"Gold set not found: {gold_path}")
        return 1
    with gold_path.open("r", encoding="utf-8") as f:
        gold = GoldSet.model_validate(json.load(f))

    workspace_id = args.workspace_id or gold.workspace_hint
    if not workspace_id:
        print("No workspace_id. Pass --workspace-id or set workspace_hint in the gold set.")
        return 1

    db = SessionLocal()
    try:
        return _run(db, gold, workspace_id, args)
    finally:
        db.close()


def _run(db, gold: GoldSet, workspace_id: str, args: argparse.Namespace) -> int:
    top_k = args.top_k
    minimal = args.minimal
    print(f"=== Retrieval Gate Evaluation ===")
    print(f"Case: {gold.case_id} | Corpus: {gold.corpus_version}")
    print(f"Workspace: {workspace_id} | Top-K: {top_k} | Minimal: {minimal}")
    print(f"Freeze: {gold.freeze.model_dump()}")

    # Resolve the paper manifest once (workspace-scoped) so unresolved refs are loud.
    all_refs = {
        q.target_paper_ref for q in gold.semantic_search
    } | {
        q.source_paper_ref for q in gold.similar_work
    } | {r.paper_ref for q in gold.counter_evidence for r in q.gold_roles} | {
        q.source_paper_ref for q in gold.counter_evidence
    } | {r for q in gold.similar_work for r in q.relevant_paper_refs}
    resolved = resolve_many(db, workspace_id, sorted(all_refs))
    unresolved = [ref for ref, pid in resolved.items() if pid is None]
    if unresolved:
        print("\n[WARN] unresolved paper refs (will be skipped):")
        for ref in unresolved:
            print(f"  - {ref}")
        if args.workspace_id is None:
            print("  (Tip: this often means the workspace_hint is wrong, or the corpus isn't indexed there.)")

    ss_entries = [run_semantic_search(db, workspace_id, q, top_k, minimal) for q in gold.semantic_search]
    sw_entries = [run_similar_work(db, workspace_id, q, top_k, minimal) for q in gold.similar_work]
    ce_entries = [run_counter_evidence(db, workspace_id, q, top_k, minimal) for q in gold.counter_evidence]

    report: dict[str, Any] = {
        "schema_version": "1.0.0",
        "case_id": gold.case_id,
        "corpus_version": gold.corpus_version,
        "workspace_id": workspace_id,
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "freeze": gold.freeze.model_dump(),
        "top_k": top_k,
        "minimal": minimal,
        "unresolved_paper_refs": unresolved,
        "gate": {},
        "semantic_search": ss_entries,
        "similar_work": sw_entries,
        "counter_evidence": ce_entries,
    }

    def valid(entries: list[dict]) -> list[dict]:
        return [e for e in entries if "recall@10" in e and isinstance(e["recall@10"], (int, float))]

    for name, entries in (("semantic_search", ss_entries), ("similar_work", sw_entries), ("counter_evidence", ce_entries)):
        valid_entries = valid(entries)
        agg = _aggregate(valid_entries, ("recall@10", "mrr@10", "diversity", "leakage"))
        threshold = GATE_THRESHOLDS[name]
        report["gate"][name] = gate_report(
            recall=agg["recall@10"] or 0.0,
            threshold=threshold,
            mrr=agg["mrr@10"],
            ndcg=None,
            diversity=agg["diversity"],
            leakage=agg["leakage"],
        )
        # Add diagnostic counts
        report["gate"][name]["queries"] = len(valid_entries)
        report["gate"][name]["resolved_queries"] = len(valid_entries)
        report["gate"][name]["unresolved_queries"] = len(entries) - len(valid_entries)

    overall_passed = all(report["gate"][name]["passed"] for name in report["gate"])
    report["gate_passed"] = overall_passed

    # Print
    print("\n=== Gate verdict ===")
    for name, block in report["gate"].items():
        status = "PASS" if block["passed"] else "FAIL"
        print(f"  [{status}] {name}: recall@{top_k}={block['recall@10']} "
              f"(threshold {block['recall_threshold']}) leakage={block['workspace_leakage']}")
    print(f"  overall: {'PASS' if overall_passed else 'FAIL'}")

    # Save
    output_path = Path(args.output) if args.output else (
        Path(__file__).parent / "reports" / f"{gold.case_id}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport saved to: {output_path}")
    return 0 if overall_passed else 2


if __name__ == "__main__":
    sys.exit(main())