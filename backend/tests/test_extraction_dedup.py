"""Unit tests for P0 exact dedup (extraction/dedup.py)."""

from __future__ import annotations

from app.workers.tasks.extraction.dedup import content_signature, dedup_exact


def _item(
    *,
    type_: str = "claim",
    name: str = "A claim",
    statement: str = "the same claim statement",
    paper_id: str = "p-1",
    start: int = 100,
    end: int = 200,
    confidence: float = 0.8,
) -> dict:
    return {
        "type": type_,
        "canonical_name": name,
        "confidence": confidence,
        "content": {"statement": statement} if type_ == "claim" else {"description": statement},
        "source_provenance": {
            "paper_id": paper_id,
            "artifact_id": f"art-{paper_id}",
            "start_char": start,
            "end_char": end,
            "batch_index": 0,
        },
        "evidence_text": statement,
    }


# ------------------------------------------------------------- content_signature
def test_content_signature_uses_statement() -> None:
    assert content_signature({"statement": "GraphRAG is better"}) == content_signature(
        {"statement": "  GraphRAG is better  "}
    )


def test_content_signature_uses_description_for_limitation() -> None:
    assert content_signature({"description": "KG is incomplete"}) == content_signature(
        {"description": "kg is incomplete"}
    )


def test_content_signature_empty_returns_stable() -> None:
    assert content_signature({}) == content_signature(None)
    assert content_signature({}) == content_signature({"statement": None})


# ------------------------------------------------------------- rule 1: exact dup
def test_exact_duplicate_keeps_first_rejects_rest() -> None:
    a = _item(statement="same fact", start=100, end=200, confidence=0.7)
    b = _item(statement="same fact", start=100, end=200, confidence=0.9)  # same everything
    survivors, rejected = dedup_exact([a, b])
    assert survivors == [a]
    assert rejected == [b]


def test_same_span_different_content_both_survive() -> None:
    a = _item(statement="claim one", start=100, end=200)
    b = _item(statement="claim two", start=100, end=200)  # same span, different fact
    survivors, rejected = dedup_exact([a, b])
    assert len(survivors) == 2
    assert rejected == []


def test_method_exact_duplicate_is_deduped() -> None:
    a = _item(type_="method", statement="PGIB is a framework", start=10, end=50)
    b = _item(type_="method", statement="PGIB is a framework", start=10, end=50)
    survivors, rejected = dedup_exact([a, b])
    assert len(survivors) == 1
    assert len(rejected) == 1


# ------------------------------------------------------------- rule 2: cross-type
def test_claim_and_limitation_same_span_keeps_higher_confidence() -> None:
    claim = _item(type_="claim", statement="position bias is present", start=7082, end=7323, confidence=0.9)
    limitation = _item(type_="limitation", statement="position bias is present", start=7082, end=7323, confidence=0.7)
    survivors, rejected = dedup_exact([claim, limitation])
    assert survivors == [claim]
    assert rejected == [limitation]


def test_claim_and_limitation_keeps_higher_even_if_second() -> None:
    limitation = _item(type_="limitation", statement="position bias is present", start=7082, end=7323, confidence=0.6)
    claim = _item(type_="claim", statement="position bias is present", start=7082, end=7323, confidence=0.95)
    survivors, rejected = dedup_exact([limitation, claim])
    # Claim has higher confidence → it replaces the limitation, which is rejected.
    assert survivors == [claim]
    assert rejected == [limitation]


def test_claim_and_limitation_equal_confidence_keeps_first() -> None:
    limitation = _item(type_="limitation", statement="position bias", start=7082, end=7323, confidence=0.8)
    claim = _item(type_="claim", statement="position bias", start=7082, end=7323, confidence=0.8)
    survivors, rejected = dedup_exact([limitation, claim])
    # Equal confidence → first (limitation) stays, claim rejected.
    assert survivors == [limitation]
    assert rejected == [claim]


# ------------------------------------------------------------- cross-paper guard
def test_same_numeric_span_different_paper_not_merged() -> None:
    a = _item(statement="same statement", paper_id="p-1", start=100, end=200)
    b = _item(statement="same statement", paper_id="p-2", start=100, end=200)
    survivors, rejected = dedup_exact([a, b])
    # Same numbers, different paper → NOT duplicates (paper key in span).
    assert len(survivors) == 2
    assert rejected == []


# ------------------------------------------------------------- no-span items
def test_items_without_span_are_kept() -> None:
    a = _item()
    a["source_provenance"] = {"paper_id": "p-1", "batch_index": 0}  # no start/end
    survivors, rejected = dedup_exact([a])
    assert survivors == [a]
    assert rejected == []


def test_empty_input() -> None:
    assert dedup_exact([]) == ([], [])


# ------------------------------------------------------------- idempotent shape
def test_survivor_plus_rejected_equals_input_count() -> None:
    items = [
        _item(statement="same", start=1, end=5),
        _item(statement="same", start=1, end=5),
        _item(statement="other", start=10, end=20),
        _item(type_="limitation", statement="other", start=10, end=20, confidence=0.9),
        _item(statement="same", paper_id="p-9", start=1, end=5),  # different paper
    ]
    survivors, rejected = dedup_exact(items)
    assert len(survivors) + len(rejected) == len(items)