"""Consistency checks for LLM outputs that cite evidence as [E1] / [E2].

The Workspace RAG prompt instructs the model to back key claims with [En]
markers that map to evidence ranks. This module validates that those markers
are real — a broken marker (referencing evidence that does not exist) means the
model hallucinated a citation, and a grounded answer with no markers at all is
a "key claims unsupported" signal. Pure functions, no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CITATION_PATTERN = re.compile(r"\[E(\d+)\]")


@dataclass
class CitationCheckResult:
    """Outcome of validating [En] markers in one text against evidence indices."""
    referenced: list[int] = field(default_factory=list)
    valid: list[int] = field(default_factory=list)
    broken: list[int] = field(default_factory=list)
    grounded_without_citations: bool = False
    ok: bool = True


def check_citation_markers(text: str, valid_indices: set[int]) -> CitationCheckResult:
    """Return referenced / valid / broken [En] markers.

    ``valid_indices`` is the set of evidence ranks that actually exist. Any
    marker whose index is not in the set is a hallucinated citation.
    """
    referenced = sorted({int(m) for m in CITATION_PATTERN.findall(text or "")})
    valid = [i for i in referenced if i in valid_indices]
    broken = [i for i in referenced if i not in valid_indices]
    return CitationCheckResult(referenced=referenced, valid=valid, broken=broken, ok=not broken)


def message_citation_check(content: str, citation_ranks: list[int], *, grounded: bool) -> CitationCheckResult:
    """Check a chat assistant message's [En] markers against its citations.

    ``grounded`` is True when the message was produced with workspace evidence
    (grounding_status == "grounded"); a grounded answer with no markers flags
    "key claims unsupported".
    """
    result = check_citation_markers(content, set(r for r in citation_ranks if r is not None))
    result.grounded_without_citations = grounded and not result.referenced
    return result
