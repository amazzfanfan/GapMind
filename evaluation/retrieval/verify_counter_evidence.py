"""Counter Evidence special validation (RG-7 / V4).

Loads a claim set (three claim types: A_fact / B_qualified / C_first_novel),
runs ``find_counter_evidence`` against a live workspace, and checks FIVE
behavioral invariants beyond raw Recall:

  1. Source exclusion  — the claim's source paper NEVER appears in results.
  2. Paper diversity   — when results exist, they span >= 2 distinct papers.
  3. Role priority     — contradicts/qualifies rank before supports/overlaps.
  4. Empty semantics   — empty top-K carries a discriminating ``empty_reason``
                         (retrieval_empty / judge_failed /
                         genuinely_no_counter_evidence), never a fake "found
                         nothing" that is actually a system failure.
  5. Judge-failure signal — a zero-confidence-unknown Judge result marks the
                         response ``degraded`` and keeps a diagnostic error.

Usage (from repo root):

    backend/.venv/Scripts/python.exe evaluation/retrieval/verify_counter_evidence.py \
        --workspace-id <uuid> \
        --gold evaluation/retrieval/gold/counter_evidence_v4.json

Exit code 0 = all invariants hold; 2 = at least one failed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
for p in (str(BACKEND_DIR), str(REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import app.db.models  # noqa: E402,F401
from app.db.session import SessionLocal  # noqa: E402
from app.domains.retrieval.service import find_counter_evidence  # noqa: E402
from evaluation.retrieval.gold_set import CounterEvidenceQuery, GoldSet  # noqa: E402
from evaluation.retrieval.run_eval import resolve_paper_ref  # noqa: E402


def _paper_ids(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        pid = getattr(item, "paper_id", None)
        if pid and pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out


def _role_rank(judgement: str) -> int:
    """Lower = higher priority; mirrors COUNTER_ROLE_PRIORITY in service.py."""
    return {"contradicts": 0, "qualifies": 1, "supports": 2, "overlaps": 2, "unknown": 3}.get(
        judgement, 99
    )


def check_claim(db, workspace_id: str, q: CounterEvidenceQuery, top_k: int, minimal: bool) -> dict[str, Any]:
    source = resolve_paper_ref(db, workspace_id, q.source_paper_ref)
    if source is None:
        return {"query_id": q.query_id, "claim_type": q.claim_type, "error": f"unresolved source: {q.source_paper_ref}", "passed": False}

    resp = find_counter_evidence(
        workspace_id,
        q.claim_text,
        top_k=top_k,
        use_reranker=True,
        use_judge=not minimal,
        exclude_paper_ids={source.id},
    )

    pids = _paper_ids(resp.items)
    roles = [getattr(i, "judgement", "unknown") for i in resp.items]
    result: dict[str, Any] = {
        "query_id": q.query_id,
        "claim_type": q.claim_type,
        "status": resp.status,
        "count": len(resp.items),
        "paper_ids": pids,
        "roles": roles,
        "empty_reason": resp.empty_reason,
        "source_paper_id": source.id,
        "passed": True,
        "checks": {},
    }

    # 1. Source exclusion
    src_ok = source.id not in pids
    result["checks"]["source_excluded"] = src_ok

    # 2. Paper diversity: with >= 2 results, they should span >= 2 distinct
    # papers (one paper's chunks shouldn't dominate the counter-evidence view).
    raw_count = len(resp.items)
    div_ok = (len(set(pids)) >= 2) if raw_count >= 2 else True
    result["checks"]["paper_diversity"] = div_ok

    # 3. Role priority: contradicts/qualifies before supports/overlaps/unknown
    role_ok = True
    for i in range(len(roles)):
        for j in range(i + 1, len(roles)):
            if _role_rank(roles[i]) > _role_rank(roles[j]):
                role_ok = False
                break
    result["checks"]["role_priority"] = role_ok

    # 4. Empty semantics
    empty_ok = True
    if not resp.items:
        # Empty top-K must be discriminated, not a fake "no counter-evidence".
        if resp.empty_reason is None:
            empty_ok = False
        elif resp.status == "failed":
            empty_ok = False  # system failure is not a clean "found nothing"
    else:
        # Non-empty: empty_reason may be None (found counter) OR set (found
        # only supports/overlaps → genuinely_no_counter_evidence).
        if resp.empty_reason == "judge_failed" and resp.status != "degraded":
            empty_ok = False
    result["checks"]["empty_semantics"] = empty_ok

    # 5. Judge-failure signal
    judge_ok = True
    if resp.status == "degraded":
        # degraded implies a zero-conf unknown (Judge failed) — keep error signal.
        judge_ok = any(r == "unknown" for r in roles)
    result["checks"]["judge_failure_signal"] = judge_ok

    result["passed"] = all(result["checks"].values())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=False)
    parser.add_argument("--gold", type=str, required=True)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--minimal", action="store_true", help="Skip LLM judge (not for the real Gate).")
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    gold_path = Path(args.gold)
    if not gold_path.exists():
        print(f"Gold set not found: {gold_path}")
        return 1
    gold = GoldSet.model_validate(json.loads(gold_path.read_text(encoding="utf-8")))

    workspace_id = args.workspace_id or gold.workspace_hint
    if not workspace_id:
        print("No workspace_id. Pass --workspace-id or set workspace_hint in gold.")
        return 1

    db = SessionLocal()
    try:
        claims = gold.counter_evidence
        if not claims:
            print("Gold set has no counter_evidence queries.")
            return 1
        by_type: dict[str, list[dict[str, Any]]] = {}
        for q in claims:
            result = check_claim(db, workspace_id, q, args.top_k, args.minimal)
            by_type.setdefault(q.claim_type or "untyped", []).append(result)

        report: dict[str, Any] = {
            "schema_version": "1.0.0",
            "case_id": gold.case_id,
            "corpus_version": gold.corpus_version,
            "workspace_id": workspace_id,
            "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "top_k": args.top_k,
            "minimal": args.minimal,
            "by_claim_type": by_type,
            "summary": {},
        }

        print("=== Counter Evidence V4 verification ===")
        overall = True
        for claim_type, results in by_type.items():
            checks = ["source_excluded", "paper_diversity", "role_priority", "empty_semantics", "judge_failure_signal"]
            per_check: dict[str, int] = {}
            for c in checks:
                per_check[c] = sum(1 for r in results if r["checks"].get(c))
            total = len(results)
            print(f"\n[{claim_type}] {total} claims")
            for c in checks:
                mark = "PASS" if per_check[c] == total else "FAIL"
                print(f"  {mark} {c}: {per_check[c]}/{total}")
                if per_check[c] != total:
                    overall = False
            report["summary"][claim_type] = {"total": total, "per_check": per_check}

        report["gate_passed"] = overall
        print(f"\nOverall: {'PASS' if overall else 'FAIL'}")

        output_path = Path(args.output) if args.output else (
            Path(__file__).parent / "reports" / f"{gold.case_id}_{time.strftime('%Y%m%d_%H%M%S')}.json"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Report saved to: {output_path}")
        return 0 if overall else 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())