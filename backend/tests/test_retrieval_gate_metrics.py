"""Unit tests for the Retrieval Gate metric functions (pure, no I/O)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# repo root so `evaluation.retrieval.metrics` is importable from backend/tests/
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evaluation.retrieval.metrics import (  # noqa: E402
    gate_report,
    mrr_at_k,
    ndcg_at_k,
    paper_diversity,
    recall_at_k,
    workspace_leakage,
)


# --------------------------------------------------------------- recall@k
def test_recall_at_k_all_hit() -> None:
    assert recall_at_k({"a", "b"}, ["a", "b", "c", "d"], k=10) == 1.0


def test_recall_at_k_partial() -> None:
    assert recall_at_k({"a", "b", "c"}, ["a", "x", "y"], k=3) == pytest.approx(1 / 3)


def test_recall_at_k_respects_k() -> None:
    # Both gold items present but the second is beyond k=1.
    assert recall_at_k({"a", "b"}, ["a", "b"], k=1) == 0.5


def test_recall_at_k_empty_gold() -> None:
    assert recall_at_k(set(), ["a"], k=10) == 0.0


def test_recall_at_k_no_hits() -> None:
    assert recall_at_k({"z"}, ["a", "b"], k=10) == 0.0


# ------------------------------------------------------------------ mrr@k
def test_mrr_first_rank_is_one() -> None:
    assert mrr_at_k({"b"}, ["b", "a"], k=10) == 1.0


def test_mrr_second_rank_is_half() -> None:
    assert mrr_at_k({"b"}, ["a", "b", "c"], k=10) == pytest.approx(0.5)


def test_mrr_zero_when_absent() -> None:
    assert mrr_at_k({"z"}, ["a", "b"], k=10) == 0.0


def test_mrr_beyond_k_counts_zero() -> None:
    # Gold is at rank 3 but we only look at top-2.
    assert mrr_at_k({"c"}, ["a", "b", "c"], k=2) == 0.0


# ------------------------------------------------------------- diversity
def test_diversity_full_when_all_distinct() -> None:
    assert paper_diversity(["a", "b", "c", "d"], k=10) == 1.0


def test_diversity_single_paper_dominates() -> None:
    assert paper_diversity(["a", "a", "a", "a"], k=10) == pytest.approx(0.25)


def test_diversity_limited_by_k() -> None:
    # Two distinct in first 2 slots out of 5 returned.
    assert paper_diversity(["a", "b", "a", "a", "a"], k=2) == 1.0


def test_diversity_empty() -> None:
    assert paper_diversity([], k=10) == 0.0


# -------------------------------------------------------------- leakage
def test_leakage_zero_when_all_match() -> None:
    assert workspace_leakage(["ws1", "ws1"], "ws1") == 0.0


def test_leakage_detects_foreign_workspace() -> None:
    assert workspace_leakage(["ws1", "ws2"], "ws1") == pytest.approx(0.5)


def test_leakage_empty_list() -> None:
    assert workspace_leakage([], "ws1") == 0.0


# ------------------------------------------------------------- gate_report
def test_gate_report_passes_when_recall_above_threshold() -> None:
    report = gate_report(recall=0.82, threshold=0.80, leakage=0.0)
    assert report["recall_passed"] is True
    assert report["passed"] is True


def test_gate_report_fails_on_leakage() -> None:
    report = gate_report(recall=0.95, threshold=0.80, leakage=0.1)
    assert report["passed"] is False  # recall fine, but leakage != 0


def test_gate_report_fails_below_threshold() -> None:
    report = gate_report(recall=0.65, threshold=0.70, leakage=0.0)
    assert report["recall_passed"] is False
    assert report["passed"] is False


def test_gate_report_uses_requested_k_in_metric_keys() -> None:
    report = gate_report(recall=0.82, threshold=0.80, k=15, mrr=0.5, ndcg=0.4)
    assert report["recall@15"] == 0.82
    assert report["mrr@15"] == 0.5
    assert report["ndcg@15"] == 0.4
    assert "recall@10" not in report
