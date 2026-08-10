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


def accumulate_tokens(run, response) -> None:
    """Accumulate LLM token usage onto a DiscoverRun (W6-3 audit).

    Adds the response's prompt/completion tokens to
    ``run.stage_summaries["token_usage"]`` so the LLM cost of a run can be
    aggregated from the run row. Safe for both gateway response objects
    (``.prompt_tokens``) and plain dicts. No-op when usage is unavailable.
    """
    prompt = getattr(response, "prompt_tokens", None)
    completion = getattr(response, "completion_tokens", None)
    if isinstance(response, dict):
        prompt = response.get("prompt_tokens", prompt)
        completion = response.get("completion_tokens", completion)
    if prompt is None and completion is None:
        return
    summary = dict(run.stage_summaries or {})
    tu = dict(summary.get("token_usage") or {})
    tu["prompt_tokens"] = int(tu.get("prompt_tokens", 0)) + int(prompt or 0)
    tu["completion_tokens"] = int(tu.get("completion_tokens", 0)) + int(completion or 0)
    tu["total_tokens"] = tu["prompt_tokens"] + tu["completion_tokens"]
    summary["token_usage"] = tu
    run.stage_summaries = summary
