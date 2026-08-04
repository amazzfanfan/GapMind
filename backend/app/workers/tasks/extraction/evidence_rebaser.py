"""Reconcile LLM-reported evidence spans against the actual parsed_markdown.

The LLM emits ``start_char``/``end_char`` and an ``evidence_text`` excerpt.
Three things can drift:

  1. the offset is wrong (batch-relative vs document-relative confusion);
  2. the text has been whitespace-normalised, so direct slice comparison fails;
  3. the LLM dropped the trailing newline, so the slice differs by 1 char.

This module resolves every drift we know about and emits a precise
``(start, end, text)`` triple pointing back into the master document, or
raises ``ValueError`` if the evidence is unrecoverable.
"""

from __future__ import annotations

import re
from typing import Any


def all_occurrences(text: str, needle: str) -> list[int]:
    """Return every index where ``needle`` appears in ``text``."""
    matches: list[int] = []
    cursor = 0
    while True:
        index = text.find(needle, cursor)
        if index < 0:
            return matches
        matches.append(index)
        cursor = index + 1


def nearest_match(matches: list[int], expected: int) -> int:
    return min(matches, key=lambda match: abs(match - expected))


def whitespace_equivalent_matches(text: str, evidence_text: str) -> list[tuple[int, int]]:
    """Find occurrences of ``evidence_text`` in ``text`` ignoring whitespace.

    Used as a fallback when the LLM collapses spaces but the document
    preserves them. Returns ``[(start, end), ...]`` offsets in ``text``.
    """
    tokens = re.split(r"\s+", evidence_text.strip())
    if not tokens or any(not token for token in tokens):
        return []
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    return [(match.start(), match.end()) for match in re.finditer(pattern, text)]


def resolve_evidence_span(
    *,
    paper_text: str,
    batch_text: str,
    batch_start: int,
    reported_start: int,
    reported_end: int,
    evidence_text: str,
) -> tuple[int, int, str]:
    """Return ``(start, end, text)`` resolved against ``paper_text``.

    ``text`` is the exact slice of ``paper_text`` between ``start`` and
    ``end`` — *not* the LLM-normalised ``evidence_text`` — so the row we
    persist matches the markdown the user sees.
    """
    relative_end = reported_start + len(evidence_text)
    if reported_start >= 0 and batch_text[reported_start:relative_end] == evidence_text:
        start = batch_start + reported_start
        return start, start + len(evidence_text), evidence_text

    if (
        reported_start >= 0
        and paper_text[reported_start : reported_start + len(evidence_text)]
        == evidence_text
    ):
        return reported_start, reported_start + len(evidence_text), evidence_text

    batch_matches = all_occurrences(batch_text, evidence_text)
    if batch_matches:
        relative_start = nearest_match(batch_matches, reported_start)
        start = batch_start + relative_start
        return start, start + len(evidence_text), evidence_text

    document_matches = all_occurrences(paper_text, evidence_text)
    if document_matches:
        expected_positions = [batch_start + reported_start, reported_start]
        start = min(
            document_matches,
            key=lambda match: min(abs(match - expected) for expected in expected_positions),
        )
        return start, start + len(evidence_text), evidence_text

    batch_whitespace_matches = whitespace_equivalent_matches(batch_text, evidence_text)
    if batch_whitespace_matches:
        relative_start, relative_end = min(
            batch_whitespace_matches,
            key=lambda match: abs(match[0] - reported_start),
        )
        start = batch_start + relative_start
        end = batch_start + relative_end
        return start, end, paper_text[start:end]

    document_whitespace_matches = whitespace_equivalent_matches(paper_text, evidence_text)
    if document_whitespace_matches:
        expected_positions = [batch_start + reported_start, reported_start]
        start, end = min(
            document_whitespace_matches,
            key=lambda match: min(abs(match[0] - expected) for expected in expected_positions),
        )
        return start, end, paper_text[start:end]

    raise ValueError(
        "evidence_text has no exact or whitespace-equivalent parsed_markdown span"
    )


__all__ = [
    "all_occurrences",
    "nearest_match",
    "resolve_evidence_span",
    "whitespace_equivalent_matches",
]