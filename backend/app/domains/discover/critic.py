"""CriticAgent (MA + W2): adversarial review + narrowing pass.

Carved out of the monolithic DiscoverService (MA-1 maintenance refactor) so
the multi-agent Critic loop (verdict → challenges → narrowing) is
self-contained and individually testable. DiscoverService instantiates one
and delegates its existing ``_critic_*`` methods to it for backward
compatibility with existing tests.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.discover.models import DiscoverRun
from app.domains.discover.ports import RetrievalPort
from app.domains.discover.schemas import DiscoverConfig
from app.domains.discover.utils import parse_json, retrieval_payload
from app.domains.retrieval.schemas import RetrievalResponse, RetrievalResultItem
from app.gateway.llm import LLMGateway

logger = get_logger(__name__)

# LLM prompt for the CriticAgent (Stage MA). After OpportunityAgent proposes
# candidates, CriticAgent adversarially reviews each against the evidence
# ledger and returns challenges + a verdict. The Orchestrator uses the verdict
# to keep, narrow, or down-weight weak opportunities — this is the visible
# "multi-agent collaboration" the demo shows (not raw model reasoning).
CRITIC_SYSTEM_PROMPT = """\
You are a rigorous, adversarial reviewer of proposed research opportunities. \
For each candidate, identify weaknesses it must address before it can be \
considered novel and viable.

Challenge categories:
- counter_evidence: the evidence ledger already contains work covering the claim
- overlap: the proposal overlaps too much with existing similar work
- assumption: a stated assumption is unsupported or brittle
- framing: the research question is too broad or ill-defined
- evaluation: the proposed validation cannot falsify the hypothesis

Rules:
- Be specific; reference the evidence roles (supporting / similar / counter / external)
- Verdict per candidate: "keep" (novel and viable), "narrow" (viable after \
tightening focus), or "reject" (not novel or fatally flawed)
- Be conservative: do not invent evidence that is not in the ledger

Output a JSON object, nothing else:
{"reviews": [{"index": 0, "verdict": "keep|narrow|reject", "challenges": ["..."], \
"suggested_narrowing": "..."}, ...]}"""

# Bounded Critic narrowing loop (MA). When the Critic marks a candidate
# "narrow", the Orchestrator runs ONE focused counter-evidence pass on the
# suggested narrower focus instead of unbounded re-synthesis. The outcome
# (obstacle found vs direction clear) is recorded on the candidate and
# surfaced to the user, keeping the multi-agent loop cheap and predictable.
MA_NARROW_MAX_ITERATIONS = 1
MA_NARROW_COUNTER_TOP_K = 8
MA_NARROW_OBSTACLE_CONFIDENCE = 0.6  # counter evidence at/above this confidence counts as an obstacle




def _make_empty_response(workspace_id: str, query: str, purpose: str) -> RetrievalResponse:
    return RetrievalResponse(
        workspace_id=workspace_id,
        query=query,
        purpose=purpose,
        status="succeeded",
        items=[],
    )


# --------------------------------------------------------------------- helpers


def collect_challenges(critic_reviews: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
    """Collect deduped challenges from narrow/reject verdicts (W2).

    Fed back into the second synthesis pass as constraints so refined
    opportunities explicitly respond to the critic's gaps.
    """
    seen: set[str] = set()
    out: list[str] = []
    for review in critic_reviews:
        if str(review.get("verdict") or "keep") not in {"narrow", "reject"}:
            continue
        for ch in review.get("challenges") or []:
            s = str(ch).strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
                if len(out) >= limit:
                    return out
    return out


def apply_reviews(
    candidates: list[dict[str, Any]], critic_reviews: list[dict[str, Any]]
) -> dict[str, int]:
    """Attach critic reviews and down-weight weak candidates.

    Returns verdict counts. ``reject`` candidates are down-weighted to at
    most 0.3 confidence and ``narrow`` to 0.45, so they surface as weaker
    opportunities without being silently dropped (HITL preserves them).
    """
    verdict_counts = {"keep": 0, "narrow": 0, "reject": 0}
    for review in critic_reviews:
        verdict = str(review.get("verdict") or "keep")
        if verdict not in verdict_counts:
            verdict = "keep"
        verdict_counts[verdict] += 1
        idx = review.get("index")
        idx = int(idx) if isinstance(idx, int) else -1
        if not (0 <= idx < len(candidates)):
            continue
        candidate = candidates[idx]
        candidate["critic_review"] = review
        confidence = float(candidate.get("confidence") or 0.5)
        candidate["confidence"] = min(
            confidence,
            0.3 if verdict == "reject" else (0.45 if verdict == "narrow" else confidence),
        )
    return verdict_counts


def narrowing_obstacle(counter: RetrievalResponse) -> bool:
    """True when focused counter evidence already covers the narrowed claim."""
    for item in counter.items:
        if (
            item.judgement in {"contradicts", "qualifies"}
            and (item.judgement_confidence or 0.0) >= MA_NARROW_OBSTACLE_CONFIDENCE
        ):
            return True
    return False


# --------------------------------------------------------------------- service


class CriticService:
    """CriticAgent orchestration: review → challenges → narrowing pass.

    Composed by ``DiscoverService``; callers should go through that
    facade so existing tests using ``service._critic_*`` keep working.
    """

    def __init__(
        self,
        db: Session,
        llm: LLMGateway,
        retrieval: RetrievalPort,
        *,
        empty_response=None,
    ) -> None:
        self.db = db
        self.llm = llm
        self.retrieval = retrieval
        self._empty = empty_response or _make_empty_response

    def review(
        self,
        run: DiscoverRun,
        claim_text: str,
        candidates: list[dict[str, Any]],
        supporting: RetrievalResponse,
        similar: RetrievalResponse,
        counter: RetrievalResponse,
    ) -> list[dict[str, Any]]:
        """Adversarially review proposed candidates (CriticAgent).

        Returns per-candidate verdicts (keep/narrow/reject) with challenges,
        used by the Orchestrator to down-weight or flag weak opportunities.
        On LLM failure it returns ``[]`` — the run keeps the candidates and
        records a critic-failed step, so the pipeline never blocks on the
        critic.
        """
        if not candidates:
            return []
        briefs = [
            f"[{i}] {str(c.get('title') or '')[:120]} — {str(c.get('problem_statement') or '')[:220]}"
            for i, c in enumerate(candidates)
        ]
        evidence_brief = {
            "supporting": [retrieval_payload(item) for item in supporting.items[:6]],
            "similar": [retrieval_payload(item) for item in similar.items[:6]],
            "counter": [retrieval_payload(item) for item in counter.items[:6]],
        }
        user_prompt = (
            f"RESEARCH QUESTION: {claim_text[:300]}\n\n"
            f"EVIDENCE LEDGER:\n{json.dumps(evidence_brief, ensure_ascii=False)}\n\n"
            f"CANDIDATES:\n" + "\n".join(briefs)
        )
        try:
            resp = self.llm.chat_completion(
                [
                    {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=2000,
                disable_thinking=True,
            )
            parsed = parse_json(resp.content)
            reviews = parsed.get("reviews") if isinstance(parsed, dict) else None
            if not isinstance(reviews, list):
                logger.warning("discover.critic_bad_shape", raw_preview=(resp.content or "")[:200])
                return []
            out: list[dict[str, Any]] = []
            for review in reviews:
                if not isinstance(review, dict) or not isinstance(review.get("index"), int):
                    continue
                idx = int(review["index"])
                if not (0 <= idx < len(candidates)):
                    continue
                verdict = str(review.get("verdict") or "keep").lower()
                if verdict not in {"keep", "narrow", "reject"}:
                    verdict = "keep"
                out.append(
                    {
                        "index": idx,
                        "verdict": verdict,
                        "challenges": [s for s in review.get("challenges") or [] if isinstance(s, str)],
                        "suggested_narrowing": str(review.get("suggested_narrowing") or ""),
                    }
                )
            return out
        except Exception as exc:
            logger.warning("discover.critic_failed", run_id=run.id, error=str(exc))
            return []

    def narrowing_pass(
        self,
        run: DiscoverRun,
        candidates: list[dict[str, Any]],
        critic_reviews: list[dict[str, Any]],
    ) -> int:
        """One bounded narrowing pass for Critic-flagged "narrow" candidates.

        For each narrow candidate with a suggested narrowing, runs a focused
        counter-evidence retrieval on the narrowed focus and records whether an
        obstacle was found. The candidate is never silently dropped — the
        outcome is recorded on ``candidate["narrowing_pass"]`` so HITL can see
        the narrowing trail. Returns the number of candidates narrowed.
        """
        by_index: dict[int, dict[str, Any]] = {}
        for review in critic_reviews:
            idx = review.get("index")
            if isinstance(idx, int):
                by_index[idx] = review
        narrow = [
            (idx, r)
            for idx, r in by_index.items()
            if r.get("verdict") == "narrow" and r.get("suggested_narrowing") and 0 <= idx < len(candidates)
        ]
        if not narrow:
            return 0
        config = DiscoverConfig.model_validate(run.config or {})
        excluded = (
            {claim_paper}
            if (claim_paper := (run.input_payload or {}).get("claim_paper_id"))
            else set()
        )
        narrowed = 0
        for idx, review in narrow:
            candidate = candidates[idx]
            narrowing = str(review.get("suggested_narrowing") or "").strip()
            base = str(candidate.get("candidate_research_question") or candidate.get("title") or "")
            query = f"{base[:300]} {narrowing[:120]}".strip()
            if not query:
                continue
            try:
                counter = self.retrieval.find_counter_evidence(
                    run.workspace_id,
                    query,
                    MA_NARROW_COUNTER_TOP_K,
                    use_reranker=config.use_reranker,
                    use_judge=config.use_judge,
                    exclude_paper_ids=excluded or None,
                )
            except Exception as exc:
                logger.warning("discover.narrowing_retrieval_failed", run_id=run.id, error=str(exc))
                counter = self._empty(run.workspace_id, query, "counter_evidence")
            obstacle = narrowing_obstacle(counter)
            candidate["narrowing_pass"] = {
                "query": query[:300],
                "counter_candidates": len(counter.items),
                "obstacle": obstacle,
                "outcome": "obstacle_found" if obstacle else "direction_clear",
            }
            if obstacle:
                candidate["confidence"] = min(float(candidate.get("confidence") or 0.5), 0.25)
            narrowed += 1
        return narrowed
