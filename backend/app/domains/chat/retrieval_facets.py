"""Deterministic query-facet planning for Workspace Chat experiments.

This module only plans candidate facet queries.  It deliberately does not
call an LLM, embedding provider, Milvus, or the database.  Production Chat
must keep the original question as the primary query; callers may use the
returned facets only after an offline A/B evaluation has justified enabling
them.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal


FacetName = Literal["formula", "method", "dataset", "comparison"]
MAX_RETRIEVAL_FACETS = 2


@dataclass(frozen=True)
class _FacetRule:
    name: FacetName
    triggers: tuple[str, ...]
    query_hint: str
    section_hints: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalFacet:
    """One deterministic facet derived from the user's original question."""

    name: FacetName
    query: str
    matched_triggers: tuple[str, ...]
    section_hints: tuple[str, ...]


_FACET_RULES: tuple[_FacetRule, ...] = (
    _FacetRule(
        name="formula",
        triggers=(
            "损失",
            "损失函数",
            "公式",
            "目标函数",
            "优化目标",
            "loss",
            "objective",
            "formula",
            "equation",
            "derivation",
        ),
        query_hint="formula equation loss objective formulation",
        section_hints=("Method", "Related Work"),
    ),
    _FacetRule(
        name="method",
        triggers=(
            "方法",
            "经典方法",
            "代表方法",
            "机制",
            "method",
            "approach",
            "mechanism",
            "architecture",
        ),
        query_hint="method approach mechanism architecture",
        section_hints=("Method", "Related Work"),
    ),
    _FacetRule(
        name="dataset",
        triggers=(
            "数据集",
            "基准数据集",
            "实验",
            "评价指标",
            "dataset",
            "benchmark",
            "experiment",
            "evaluation",
            "metrics",
        ),
        query_hint="dataset benchmark experiment evaluation metrics",
        section_hints=("Experiment", "Method"),
    ),
    _FacetRule(
        name="comparison",
        triggers=(
            "比较",
            "对比",
            "基线",
            "优于",
            "compare",
            "comparison",
            "baseline",
            "versus",
        ),
        query_hint="baseline comparison related work differences",
        section_hints=("Experiment", "Related Work"),
    ),
)


def _contains_trigger(question: str, trigger: str) -> bool:
    if trigger.isascii() and trigger.replace("_", "").replace("-", "").isalnum():
        return re.search(rf"(?<![a-z0-9]){re.escape(trigger)}(?![a-z0-9])", question) is not None
    return trigger in question


def plan_retrieval_facets(question: str) -> tuple[RetrievalFacet, ...]:
    """Return at most two deterministic facets for ``question``.

    The rule order is intentional and stable: formula questions are handled
    before method, dataset, and comparison facets.  The original normalized
    question is copied into every planned query, so a future caller cannot
    accidentally replace the primary query with a keyword-only query.
    """

    normalized = " ".join(question.split()).strip().casefold()
    if not normalized:
        return ()

    facets: list[RetrievalFacet] = []
    for rule in _FACET_RULES:
        matched = tuple(trigger for trigger in rule.triggers if _contains_trigger(normalized, trigger))
        if not matched:
            continue
        facets.append(
            RetrievalFacet(
                name=rule.name,
                query=f"{normalized}\n检索重点：{rule.query_hint}",
                matched_triggers=matched,
                section_hints=rule.section_hints,
            )
        )
        if len(facets) >= MAX_RETRIEVAL_FACETS:
            break
    return tuple(facets)


__all__ = ["FacetName", "MAX_RETRIEVAL_FACETS", "RetrievalFacet", "plan_retrieval_facets"]
