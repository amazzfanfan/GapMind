"""Shared pure helpers for the discover domain (MA-1).

Carved out so critic.py / synthesis.py / external_retrieval.py each import the
same ``parse_json`` / ``retrieval_payload`` instead of duplicating them. This
module is a leaf: it imports only stdlib + ``retrieval.schemas``, so none of
the sibling service modules depend on it in a way that creates a cycle.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.domains.retrieval.schemas import RetrievalResultItem


def parse_json(content: str) -> dict[str, Any] | None:
    """Parse an LLM JSON response; tolerate a code-fence / extra text fallback."""
    try:
        value = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def retrieval_payload(item: RetrievalResultItem) -> dict[str, Any]:
    """Compact retrieval item used in synthesis/critic prompts and audit trails."""
    return {
        "paper_id": item.paper_id,
        "title": item.paper_title,
        "text": item.text[:900],
        "score": item.score,
        "judgement": item.judgement,
        "evidence_level": item.evidence_level,
    }
