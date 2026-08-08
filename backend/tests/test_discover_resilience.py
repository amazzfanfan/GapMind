"""W5 resilience tests: idempotency + degradation-continue.

Covers two real gaps: execute_run must be idempotent for terminal runs
(W5-6, protects against duplicate spawns), and an Opportunity synthesis LLM
failure must degrade to a rule-based fallback instead of failing the pipeline
(W5-5). The other degradation paths (S2 429, Milvus down, PDF download fail,
critic/role LLM down) already have coverage in test_discover_external_queries,
test_retrieval_lifecycle, test_discover_fulltext, test_discover_agents, and
test_discover_external_role.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.domains.discover.models import DiscoverRun  # noqa: E402
from app.domains.discover.service import DiscoverService  # noqa: E402
from app.domains.retrieval.schemas import RetrievalResponse  # noqa: E402
from app.domains.workspace.models import Workspace  # noqa: E402


class _BoomLLM:
    def chat_completion(self, messages, **kwargs):
        raise RuntimeError("llm down")


class _NoopLLM:
    def chat_completion(self, messages, **kwargs):
        return SimpleNamespace(content=json.dumps({"opportunities": []}))


def _service(db, llm=None) -> DiscoverService:
    return DiscoverService(db, llm=llm or _NoopLLM())


def _ws(db) -> Workspace:
    ws = Workspace(id=str(uuid4()), name="ws")
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def _run(db, ws: Workspace, **overrides) -> DiscoverRun:
    kwargs = {
        "id": str(uuid4()),
        "workspace_id": ws.id,
        "status": "queued",
        "input_payload": {},
        "scope": {},
        "config": {},
        "stage_summaries": {},
    }
    kwargs.update(overrides)
    run = DiscoverRun(**kwargs)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _empty(workspace_id: str, purpose: str) -> RetrievalResponse:
    return RetrievalResponse(workspace_id=workspace_id, purpose=purpose, status="succeeded", items=[])


def test_execute_run_is_idempotent_for_terminal_status(db_session):
    ws = _ws(db_session)
    run = _run(db_session, ws, status="succeeded", stage="saved", progress=1.0)

    result = _service(db_session).execute_run(run.id)

    assert result["idempotent"] is True
    assert result["status"] == "succeeded"
    # A duplicate spawn must not re-run the pipeline or touch the run row.
    db_session.refresh(run)
    assert run.status == "succeeded"


def test_execute_run_is_idempotent_for_cancelled(db_session):
    ws = _ws(db_session)
    run = _run(db_session, ws, status="cancelled")

    result = _service(db_session).execute_run(run.id)

    assert result["idempotent"] is True
    assert result["status"] == "cancelled"


def test_synthesis_llm_failure_degrades_to_rule_based_fallback(db_session):
    ws = _ws(db_session)
    run = _run(db_session, ws)
    gate = {"verified": False, "confirmable": False, "evidence_coverage": 0.0}

    svc = _service(db_session, llm=_BoomLLM())
    candidates = svc._synthesize_candidates(
        run,
        "topic",
        _empty(ws.id, "supporting"),
        _empty(ws.id, "similar"),
        _empty(ws.id, "counter"),
        _empty(ws.id, "external_full_text"),
        gate,
        3,
    )

    # Pipeline continues with a conservative rule-based candidate instead of failing.
    assert len(candidates) == 1
    assert candidates[0]["provider"] == "rule_based_fallback"
    assert candidates[0]["verification_status"] == "verification_incomplete"


def test_external_candidate_state_skips_non_imported_rows(db_session):
    """Verified query without imported rows must not crash state aggregation."""
    ws = _ws(db_session)
    run = _run(db_session, ws)
    from app.domains.discover.models import DiscoverExternalCandidate

    db_session.add(
        DiscoverExternalCandidate(
            id=str(uuid4()), discover_run_id=run.id, query="q", rank=1,
            external_paper_id="S2-1", title="T", authors=[], verification_status="selected",
            evidence_level="metadata_only", snapshot_payload={},
        )
    )
    db_session.commit()

    state = _service(db_session)._external_candidate_state(run)
    assert state["selected"] == 1
    assert state["verified"] == 0
    assert state["failed"] == 0
