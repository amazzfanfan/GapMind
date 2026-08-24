"""Tests for deterministic Chat retrieval facet planning."""

from __future__ import annotations

from app.domains.chat.retrieval_facets import (
    MAX_RETRIEVAL_FACETS,
    plan_retrieval_facets,
)


def test_formula_facet_preserves_the_normalized_primary_question() -> None:
    facets = plan_retrieval_facets("  GIB 的优化目标，分析一下它的公式  ")

    assert [facet.name for facet in facets] == ["formula"]
    assert facets[0].query.startswith("gib 的优化目标，分析一下它的公式")
    assert "formula equation loss objective formulation" in facets[0].query
    assert facets[0].section_hints == ("Method", "Related Work")
    assert "优化目标" in facets[0].matched_triggers
    assert "公式" in facets[0].matched_triggers


def test_method_and_comparison_facets_have_stable_order_and_limit() -> None:
    facets = plan_retrieval_facets("比较经典方法与基线的机制、实验结果和公式")

    assert len(facets) == MAX_RETRIEVAL_FACETS
    assert [facet.name for facet in facets] == ["formula", "method"]
    assert all("比较经典方法与基线的机制、实验结果和公式" in facet.query for facet in facets)


def test_dataset_and_comparison_facets_are_distinct() -> None:
    facets = plan_retrieval_facets("比较两个模型在 Cora 数据集上的实验结果")

    assert [facet.name for facet in facets] == ["dataset", "comparison"]
    assert facets[0].section_hints == ("Experiment", "Method")
    assert facets[1].section_hints == ("Experiment", "Related Work")


def test_stability_question_without_facet_terms_returns_no_facet() -> None:
    assert plan_retrieval_facets("分布偏移下 GNN 解释的稳定性如何？") == ()


def test_english_word_matching_does_not_match_longer_words() -> None:
    assert plan_retrieval_facets("methodology overview") == ()
    assert [facet.name for facet in plan_retrieval_facets("method overview")] == ["method"]


def test_empty_question_returns_no_facet() -> None:
    assert plan_retrieval_facets(" \n\t ") == ()
