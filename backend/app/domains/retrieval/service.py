"""Retrieval service layer - chunk indexing and semantic search.

Step ④: Read chunks JSONL (Contract B) → embed via BGE-M3 → insert Milvus.
Step ⑤: semantic_search / find_similar_work / find_counter_evidence (Phase 3).

Pipeline stages (Contract D retrieval_stage):
  candidate_recall → reranked → llm_judged
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from app.core.config import settings
from app.core.logging import get_logger
from app.domains.retrieval import milvus_client
from app.domains.retrieval.schemas import (
    ChunkRecord,
    IndexChunksResult,
    RetrievalResponse,
    RetrievalResultItem,
)
from app.gateway.embedding import get_embedding_gateway
from app.gateway.judge import get_judgement_gateway
from app.gateway.reranker import get_reranker_gateway

logger = get_logger(__name__)

# Chunks JSONL root: backend/data/chunks/{workspace_id}/{paper_id}.jsonl
DATA_ROOT = Path(__file__).resolve().parents[3] / "data" / "chunks"


# ==================================================================
# Step ④: Index paper chunks into Milvus
# ==================================================================


def index_paper_chunks(
    workspace_id: str,
    paper_id: str,
    *,
    force_reindex: bool = False,
) -> IndexChunksResult:
    """Main entry: load chunks JSONL → embed → insert into Milvus.

    Idempotent: skips chunks already indexed unless force_reindex=True.
    """
    start_time = time.perf_counter()
    gateway = get_embedding_gateway()

    result = IndexChunksResult(
        workspace_id=workspace_id,
        paper_id=paper_id,
        embedding_model=gateway.model,
        embedding_dim=gateway.dim,
    )

    # 1. Load chunks from JSONL
    chunks = _load_chunks_jsonl(workspace_id, paper_id)
    if not chunks:
        result.error = f"No chunks found for paper {paper_id}"
        logger.warning("index.no_chunks", workspace_id=workspace_id, paper_id=paper_id)
        return result

    result.total_chunks = len(chunks)

    # 2. Idempotency: skip already-indexed chunks
    if force_reindex:
        milvus_client.delete_by_paper(paper_id)
        to_index = chunks
    else:
        existing_ids = milvus_client.get_existing_chunk_ids(paper_id)
        to_index = [c for c in chunks if c.chunk_id not in existing_ids]
        result.skipped_count = len(chunks) - len(to_index)

    if not to_index:
        result.indexed_count = 0
        result.duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "index.all_skipped",
            paper_id=paper_id,
            skipped=result.skipped_count,
        )
        return result

    # 3. Embed texts via BGE-M3
    texts = [c.text for c in to_index]
    logger.info(
        "index.embedding_start",
        paper_id=paper_id,
        chunk_count=len(texts),
    )
    embedding_result = gateway.embed_texts(texts)

    # 4. Build Milvus records
    records: list[dict[str, Any]] = []
    for chunk, vector in zip(to_index, embedding_result.embeddings):
        records.append({
            "chunk_id": chunk.chunk_id,
            "workspace_id": chunk.workspace_id,
            "paper_id": chunk.paper_id,
            "source_artifact_id": chunk.source_artifact_id,
            "chunk_index": chunk.chunk_index,
            "section": chunk.section or "Unknown",
            "text": chunk.text[:8000],  # Milvus VARCHAR(8192) safety margin
            "tokens_estimate": chunk.tokens_estimate,
            "embedding": vector,
        })

    # 5. Insert into Milvus (batch to avoid single huge request)
    batch_size = 100
    total_inserted = 0
    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        total_inserted += milvus_client.insert_chunks(batch)

    result.indexed_count = total_inserted
    result.duration_ms = (time.perf_counter() - start_time) * 1000

    logger.info(
        "index.completed",
        paper_id=paper_id,
        workspace_id=workspace_id,
        indexed=result.indexed_count,
        skipped=result.skipped_count,
        duration_ms=round(result.duration_ms, 1),
    )
    return result


def _load_chunks_jsonl(workspace_id: str, paper_id: str) -> list[ChunkRecord]:
    """Read and validate chunks from the JSONL file (Contract B)."""
    jsonl_path = DATA_ROOT / workspace_id / f"{paper_id}.jsonl"
    if not jsonl_path.exists():
        logger.warning("index.jsonl_not_found", path=str(jsonl_path))
        return []

    chunks: list[ChunkRecord] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                chunk = ChunkRecord.model_validate(raw)
                chunks.append(chunk)
            except (json.JSONDecodeError, ValidationError) as e:
                logger.warning(
                    "index.invalid_chunk_line",
                    path=str(jsonl_path),
                    line=line_num,
                    error=str(e)[:200],
                )
    return chunks


# ==================================================================
# Step ⑤: Retrieval functions (Contract D output)
# ==================================================================


def semantic_search(
    workspace_id: str,
    query: str,
    top_k: int = 10,
    *,
    section: str | None = None,
    use_reranker: bool = True,
) -> RetrievalResponse:
    """General semantic search within a workspace.

    Pipeline: vector recall → (optional) rerank → return.
    """
    start_time = time.perf_counter()
    request_id = str(uuid4())
    gateway = get_embedding_gateway()

    try:
        # Stage 1: Vector recall (over-fetch for reranker)
        recall_k = top_k * 3 if use_reranker else top_k
        query_vector = gateway.embed_one(query)
        hits = milvus_client.search(
            query_vector,
            workspace_id,
            top_k=recall_k,
            section=section,
        )

        if not hits:
            latency = (time.perf_counter() - start_time) * 1000
            return RetrievalResponse(
                request_id=request_id,
                workspace_id=workspace_id,
                query=query,
                purpose="semantic",
                status="succeeded",
                items=[],
                total=0,
                latency_ms=round(latency, 2),
            )

        # Stage 2: Rerank
        if use_reranker and len(hits) > 1:
            items = _rerank_hits(query, hits, top_k)
        else:
            items = [_hit_to_result_item(hit) for hit in hits[:top_k]]

        latency = (time.perf_counter() - start_time) * 1000
        return RetrievalResponse(
            request_id=request_id,
            workspace_id=workspace_id,
            query=query,
            purpose="semantic",
            status="succeeded",
            items=items,
            total=len(items),
            latency_ms=round(latency, 2),
            filters_applied={"section": section} if section else {},
        )
    except Exception as e:
        latency = (time.perf_counter() - start_time) * 1000
        logger.error("retrieval.semantic_search_failed", error=str(e))
        return RetrievalResponse(
            request_id=request_id,
            workspace_id=workspace_id,
            query=query,
            purpose="semantic",
            status="failed",
            latency_ms=round(latency, 2),
            error=str(e),
        )


def find_similar_work(
    workspace_id: str,
    paper_id: str,
    top_k: int = 10,
    *,
    use_reranker: bool = True,
) -> RetrievalResponse:
    """Find chunks from other papers that are similar to the given paper.

    Pipeline: multi-vector recall → exclude same paper → (optional) rerank → return.
    Uses the paper's own chunks as queries (multi-vector recall).
    """
    start_time = time.perf_counter()
    request_id = str(uuid4())
    gateway = get_embedding_gateway()

    try:
        # Load representative chunks from the target paper as queries
        chunks = _load_chunks_jsonl(workspace_id, paper_id)
        if not chunks:
            return RetrievalResponse(
                request_id=request_id,
                workspace_id=workspace_id,
                query=f"paper:{paper_id}",
                purpose="similar_work",
                status="failed",
                error=f"No chunks found for paper {paper_id}",
            )

        # Use up to 5 representative chunks (spread across the paper)
        sample_indices = _spread_sample_indices(len(chunks), max_samples=5)
        query_texts = [chunks[i].text for i in sample_indices]

        # Embed all query chunks
        embed_result = gateway.embed_texts(query_texts)

        # Search for each, collect hits excluding same paper
        seen_chunk_ids: set[str] = set()
        all_hits: list[dict[str, Any]] = []

        for vector in embed_result.embeddings:
            hits = milvus_client.search(
                vector,
                workspace_id,
                top_k=top_k * 2,  # over-fetch to account for same-paper filtering
            )
            for hit in hits:
                hit_paper_id = hit.get("paper_id", "")
                hit_chunk_id = hit.get("chunk_id", "")
                if hit_paper_id == paper_id:
                    continue
                if hit_chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(hit_chunk_id)
                all_hits.append(hit)

        if not all_hits:
            latency = (time.perf_counter() - start_time) * 1000
            return RetrievalResponse(
                request_id=request_id,
                workspace_id=workspace_id,
                query=f"paper:{paper_id}",
                purpose="similar_work",
                status="succeeded",
                items=[],
                total=0,
                latency_ms=round(latency, 2),
            )

        # Rerank using the first representative chunk as query text
        if use_reranker and len(all_hits) > 1:
            rerank_query = query_texts[0][:500]
            items = _rerank_hits(rerank_query, all_hits, top_k)
        else:
            # Sort by vector score descending
            all_hits.sort(key=lambda h: h.get("score", 0.0), reverse=True)
            items = [_hit_to_result_item(hit) for hit in all_hits[:top_k]]

        latency = (time.perf_counter() - start_time) * 1000
        return RetrievalResponse(
            request_id=request_id,
            workspace_id=workspace_id,
            query=f"paper:{paper_id}",
            purpose="similar_work",
            status="succeeded",
            items=items,
            total=len(items),
            latency_ms=round(latency, 2),
        )
    except Exception as e:
        latency = (time.perf_counter() - start_time) * 1000
        logger.error("retrieval.similar_work_failed", error=str(e))
        return RetrievalResponse(
            request_id=request_id,
            workspace_id=workspace_id,
            query=f"paper:{paper_id}",
            purpose="similar_work",
            status="failed",
            latency_ms=round(latency, 2),
            error=str(e),
        )


def find_counter_evidence(
    workspace_id: str,
    claim_text: str,
    top_k: int = 10,
    *,
    use_reranker: bool = True,
    use_judge: bool = True,
) -> RetrievalResponse:
    """Find chunks that may contradict or qualify a given claim.

    Pipeline: vector recall → rerank → LLM/NLI judge → return.
    Contract D requirement: counter_evidence MUST pass through rerank or
    LLM/NLI judgement. retrieval_stage = 'llm_judged' when judge is used.
    """
    start_time = time.perf_counter()
    request_id = str(uuid4())
    gateway = get_embedding_gateway()

    try:
        # Stage 1: Vector recall (over-fetch)
        recall_k = top_k * 3 if (use_reranker or use_judge) else top_k
        query_vector = gateway.embed_one(claim_text)
        hits = milvus_client.search(
            query_vector,
            workspace_id,
            top_k=recall_k,
        )

        if not hits:
            latency = (time.perf_counter() - start_time) * 1000
            return RetrievalResponse(
                request_id=request_id,
                workspace_id=workspace_id,
                query=claim_text,
                purpose="counter_evidence",
                status="succeeded",
                items=[],
                total=0,
                latency_ms=round(latency, 2),
            )

        # Stage 2: Rerank
        if use_reranker and len(hits) > 1:
            reranked_items = _rerank_hits(claim_text, hits, top_k)
        else:
            reranked_items = [_hit_to_result_item(hit) for hit in hits[:top_k]]

        # Stage 3: LLM Judgement (NLI classification)
        if use_judge and reranked_items:
            items = _judge_items(claim_text, reranked_items)
        else:
            items = reranked_items

        latency = (time.perf_counter() - start_time) * 1000

        # Determine status: degraded if judge failed
        status = "succeeded"
        if use_judge and any(i.judgement == "unknown" and i.judgement_confidence == 0.0 for i in items):
            # Some judgements failed, but we still have results
            status = "degraded" if all(i.judgement == "unknown" for i in items) else "succeeded"

        return RetrievalResponse(
            request_id=request_id,
            workspace_id=workspace_id,
            query=claim_text,
            purpose="counter_evidence",
            status=status,
            items=items,
            total=len(items),
            latency_ms=round(latency, 2),
        )
    except Exception as e:
        latency = (time.perf_counter() - start_time) * 1000
        logger.error("retrieval.counter_evidence_failed", error=str(e))
        return RetrievalResponse(
            request_id=request_id,
            workspace_id=workspace_id,
            query=claim_text,
            purpose="counter_evidence",
            status="failed",
            latency_ms=round(latency, 2),
            error=str(e),
        )


# ==================================================================
# Internal pipeline stages
# ==================================================================


def _rerank_hits(
    query: str,
    hits: list[dict[str, Any]],
    top_k: int,
) -> list[RetrievalResultItem]:
    """Rerank Milvus hits using cross-encoder, return top_k items."""
    reranker = get_reranker_gateway()
    documents = [hit.get("text", "") for hit in hits]

    try:
        rerank_result = reranker.rerank(query, documents, top_n=top_k)
    except Exception as e:
        # Graceful degradation: fall back to vector score ordering
        logger.warning("retrieval.rerank_failed_fallback", error=str(e))
        hits_sorted = sorted(hits, key=lambda h: h.get("score", 0.0), reverse=True)
        return [_hit_to_result_item(hit) for hit in hits_sorted[:top_k]]

    # Map reranked indices back to hits
    items: list[RetrievalResultItem] = []
    for rerank_hit in rerank_result.hits[:top_k]:
        if rerank_hit.index < len(hits):
            original_hit = hits[rerank_hit.index]
            item = _hit_to_result_item(original_hit, retrieval_stage="reranked")
            item.score = rerank_hit.relevance_score
            items.append(item)

    return items


def _judge_items(
    claim: str,
    items: list[RetrievalResultItem],
) -> list[RetrievalResultItem]:
    """Apply LLM judgement to reranked items (counter_evidence only)."""
    judge = get_judgement_gateway()
    passages = [item.text for item in items]

    judgement_result = judge.judge_batch(claim, passages)

    # Apply judgement to items
    for hit in judgement_result.hits:
        if hit.index < len(items):
            items[hit.index].judgement = hit.judgement
            items[hit.index].judgement_confidence = hit.confidence
            items[hit.index].retrieval_stage = "llm_judged"

    return items


# ==================================================================
# Helpers
# ==================================================================


def _hit_to_result_item(
    hit: dict[str, Any],
    *,
    retrieval_stage: str = "candidate_recall",
) -> RetrievalResultItem:
    """Convert a Milvus search hit to a RetrievalResultItem."""
    return RetrievalResultItem(
        result_id=str(uuid4()),
        source_scope="workspace",
        evidence_level="full_text",
        paper_id=hit.get("paper_id"),
        chunk_id=hit.get("chunk_id"),
        artifact_id=hit.get("source_artifact_id"),
        section=hit.get("section"),
        text=hit.get("text", ""),
        score=hit.get("score", 0.0),
        retrieval_stage=retrieval_stage,
    )


def _spread_sample_indices(total: int, max_samples: int = 5) -> list[int]:
    """Pick evenly spread indices from [0, total) for representative sampling."""
    if total <= max_samples:
        return list(range(total))
    step = total / max_samples
    return [int(i * step) for i in range(max_samples)]
