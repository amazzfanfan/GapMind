"""Retrieval HTTP API router.

Endpoints (per api_reference.md "Retrieval（计划）"):
  POST /api/v1/workspaces/{wid}/retrieval/search            semantic search
  POST /api/v1/workspaces/{wid}/retrieval/similar-work      find similar work for a paper
  POST /api/v1/workspaces/{wid}/retrieval/counter-evidence  find counter-evidence for a claim
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.domains.retrieval.schemas import RetrievalResponse
from app.domains.retrieval.service import (
    find_counter_evidence,
    find_similar_work,
    semantic_search,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/retrieval", tags=["retrieval"])


# ------------------------------------------------------------------
# Request schemas
# ------------------------------------------------------------------


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=50)
    section: str | None = None
    use_reranker: bool = True


class SimilarWorkRequest(BaseModel):
    paper_id: str
    top_k: int = Field(default=10, ge=1, le=50)
    use_reranker: bool = True


class CounterEvidenceRequest(BaseModel):
    claim_text: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=10, ge=1, le=50)
    use_reranker: bool = True
    use_judge: bool = True


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------


@router.post("/search", response_model=RetrievalResponse)
def api_semantic_search(workspace_id: str, body: SearchRequest) -> RetrievalResponse:
    """Semantic search over workspace paper chunks."""
    result = semantic_search(
        workspace_id=workspace_id,
        query=body.query,
        top_k=body.top_k,
        section=body.section,
        use_reranker=body.use_reranker,
    )
    if result.status == "failed":
        raise HTTPException(status_code=502, detail=result.error or "Retrieval failed")
    return result


@router.post("/similar-work", response_model=RetrievalResponse)
def api_similar_work(workspace_id: str, body: SimilarWorkRequest) -> RetrievalResponse:
    """Find similar work from other papers in the workspace."""
    result = find_similar_work(
        workspace_id=workspace_id,
        paper_id=body.paper_id,
        top_k=body.top_k,
        use_reranker=body.use_reranker,
    )
    if result.status == "failed":
        raise HTTPException(status_code=502, detail=result.error or "Retrieval failed")
    return result


@router.post("/counter-evidence", response_model=RetrievalResponse)
def api_counter_evidence(workspace_id: str, body: CounterEvidenceRequest) -> RetrievalResponse:
    """Find counter-evidence for a claim (reranked + LLM judged)."""
    result = find_counter_evidence(
        workspace_id=workspace_id,
        claim_text=body.claim_text,
        top_k=body.top_k,
        use_reranker=body.use_reranker,
        use_judge=body.use_judge,
    )
    if result.status == "failed":
        raise HTTPException(status_code=502, detail=result.error or "Retrieval failed")
    return result
