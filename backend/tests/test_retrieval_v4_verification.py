"""Counter Evidence V4 verification logic tests (RG-7).

The V4 runner (`evaluation/retrieval/verify_counter_evidence.py`) checks five
behavioral invariants on top of raw Recall. These tests validate that logic
with a mocked ``find_counter_evidence`` so the invariant-checking code can be
regression-tested without a live Milvus corpus.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evaluation.retrieval.gold_set import GoldSet  # noqa: E402
from evaluation.retrieval.verify_counter_evidence import (  # noqa: E402
    _role_rank,
    check_claim,
)

from app.domains.retrieval.schemas import RetrievalResponse, RetrievalResultItem  # noqa: E402


# ------------------------------------------------------------- role_rank
def test_role_rank_orders_user_facing_signal() -> None:
    assert _role_rank("contradicts") < _role_rank("qualifies")
    assert _role_rank("qualifies") < _role_rank("supports")
    assert _role_rank("supports") == _role_rank("overlaps")
    assert _role_rank("overlaps") < _role_rank("unknown")


def test_role_rank_unknown_fallback() -> None:
    assert _role_rank("not-a-real-role") == 99  # default guard


# ------------------------------------------------------------- check_claim
def _resp(items: list[RetrievalResultItem], **overrides) -> RetrievalResponse:
    base = dict(
        workspace_id="ws-1",
        query="claim",
        purpose="counter_evidence",
        status="succeeded",
        items=items,
        total=len(items),
        empty_reason=None,
    )
    base.update(overrides)
    return RetrievalResponse.model_validate(base)


def _item(paper_id: str, judgement: str = "contradicts", confidence: float = 0.9) -> RetrievalResultItem:
    return RetrievalResultItem(
        result_id=f"r-{paper_id}",
        paper_id=paper_id,
        judgement=judgement,
        judgement_confidence=confidence,
        text="t",
    )


@pytest.fixture
def _patch(monkeypatch):
    """Patch find_counter_evidence + paper-ref resolution in the module."""
    def _install(resp: RetrievalResponse, *, source_paper_id: str = "p-src"):
        from types import SimpleNamespace
        fake = MagicMock(return_value=resp)
        monkeypatch.setattr(
            "evaluation.retrieval.verify_counter_evidence.find_counter_evidence", fake
        )
        monkeypatch.setattr(
            "evaluation.retrieval.verify_counter_evidence.resolve_paper_ref",
            lambda db, wid, ref: SimpleNamespace(id=source_paper_id, title=ref),
        )
        return fake

    return _install


def test_check_claim_source_exclusion_fails_when_source_leaks(_patch) -> None:
    # Source paper leaked into results — the strongest failure.
    resp = _resp([_item("p-src"), _item("p-other")])
    _patch(resp, source_paper_id="p-src")
    result = check_claim(None, "ws-1", _q(), top_k=10, minimal=False)
    assert result["checks"]["source_excluded"] is False
    assert result["passed"] is False


def test_check_claim_paper_diversity_fails_when_single_paper_dominates(_patch) -> None:
    resp = _resp([_item("p-a"), _item("p-a"), _item("p-a")])
    _patch(resp, source_paper_id="p-src")
    result = check_claim(None, "ws-1", _q(), top_k=10, minimal=False)
    assert result["checks"]["paper_diversity"] is False
    assert result["passed"] is False


def test_check_claim_role_priority_fails_when_supports_before_contradicts(_patch) -> None:
    # supports before contradicts violates the user-facing ordering.
    resp = _resp([_item("p-a", "supports"), _item("p-b", "contradicts")])
    _patch(resp, source_paper_id="p-src")
    result = check_claim(None, "ws-1", _q(), top_k=10, minimal=False)
    assert result["checks"]["role_priority"] is False
    assert result["passed"] is False


def test_check_claim_empty_semantics_requires_reason(_patch) -> None:
    # Empty top-K with no empty_reason = fake "found nothing".
    resp = _resp([], empty_reason=None)
    _patch(resp, source_paper_id="p-src")
    result = check_claim(None, "ws-1", _q(), top_k=10, minimal=False)
    assert result["checks"]["empty_semantics"] is False


def test_check_claim_empty_semantics_ok_when_reason_set(_patch) -> None:
    resp = _resp([], status="succeeded", empty_reason="genuinely_no_counter_evidence")
    _patch(resp, source_paper_id="p-src")
    result = check_claim(None, "ws-1", _q(), top_k=10, minimal=False)
    assert result["checks"]["empty_semantics"] is True
    # A clean "found nothing" is not a failure — passes the invariant.
    assert result["passed"] is True


def test_check_claim_judge_failure_signal(_patch) -> None:
    # degraded status must coincide with a zero-confidence unknown role.
    resp = _resp(
        [_item("p-a", "unknown", confidence=0.0)],
        status="degraded",
        empty_reason="judge_failed",
    )
    _patch(resp, source_paper_id="p-src")
    result = check_claim(None, "ws-1", _q(), top_k=10, minimal=False)
    assert result["checks"]["judge_failure_signal"] is True
    assert result["status"] == "degraded"


def test_check_claim_degraded_without_unknown_role_is_inconsistent(_patch) -> None:
    # degraded but no unknown role → the signal is inconsistent.
    resp = _resp([_item("p-a", "contradicts", confidence=0.9)], status="degraded")
    _patch(resp, source_paper_id="p-src")
    result = check_claim(None, "ws-1", _q(), top_k=10, minimal=False)
    assert result["checks"]["judge_failure_signal"] is False


def _q() -> Any:
    from evaluation.retrieval.gold_set import CounterEvidenceQuery
    return CounterEvidenceQuery(
        query_id="test-q",
        claim_text="some claim text that is long enough",
        source_paper_ref="Source Paper",
        gold_roles=[{"paper_ref": "Other Paper", "role": "contradicts"}],
        claim_type="C_first_novel",
    )


# ------------------------------------------------------------- gold set shape
def test_v4_gold_set_has_three_types_each_five() -> None:
    path = _REPO_ROOT / "evaluation" / "retrieval" / "gold" / "counter_evidence_v4.json"
    gold = GoldSet.model_validate(
        __import__("json").loads(path.read_text(encoding="utf-8"))
    )
    from collections import Counter
    types = Counter(q.claim_type for q in gold.counter_evidence)
    assert len(gold.counter_evidence) == 15
    assert types["A_fact"] == 5
    assert types["B_qualified"] == 5
    assert types["C_first_novel"] == 5