"""Retrieval domain Pydantic schemas.

Defines the data structures for chunk indexing (Contract B input)
and retrieval responses (Contract D output).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# Contract B: Chunk record (input from parse_pdf JSONL)
# ------------------------------------------------------------------


class ChunkRecord(BaseModel):
    """A single chunk from data/chunks/{workspace_id}/{paper_id}.jsonl.

    Validates against Contract B (data_contracts_v1.md §3).
    """

    schema_version: str = "1.0.0"
    chunk_id: str
    workspace_id: str
    paper_id: str
    source_artifact_id: str
    source_artifact_kind: str = "parsed_text"
    chunk_index: int
    section: str | None = None
    subsection: str | None = None
    text: str
    start_char: int
    end_char: int
    page_start: int = 0
    page_end: int = 0
    tokens_estimate: int = 0
    chunk_version: str = "v1"
    created_at: str = ""


# ------------------------------------------------------------------
# Indexing result
# ------------------------------------------------------------------


class IndexChunksResult(BaseModel):
    """Result of indexing one paper's chunks into Milvus."""

    workspace_id: str
    paper_id: str
    total_chunks: int = 0
    indexed_count: int = 0
    skipped_count: int = 0
    embedding_model: str = ""
    embedding_dim: int = 0
    duration_ms: float = 0.0
    error: str | None = None


# ------------------------------------------------------------------
# Contract D: Retrieval response (output to Discover Agent / UI)
# ------------------------------------------------------------------


class RetrievalResultItem(BaseModel):
    """A single retrieval hit (Contract D item)."""

    result_id: str = ""
    source_scope: str = "workspace"  # workspace | external
    evidence_level: str = "full_text"  # full_text | metadata_only
    paper_id: str | None = None
    external_paper_id: str | None = None
    paper_title: str | None = None
    paper_year: int | None = None
    chunk_id: str | None = None
    artifact_id: str | None = None
    section: str | None = None
    text: str = ""
    score: float = 0.0
    retrieval_stage: str = "candidate_recall"
    judgement: str = "unknown"
    judgement_confidence: float = 0.0


class RetrievalResponse(BaseModel):
    """Full retrieval response (Contract D)."""

    schema_version: str = "1.0.0"
    request_id: str = ""
    workspace_id: str
    query: str = ""
    purpose: str = "semantic"  # semantic | similar_work | counter_evidence
    status: str = "succeeded"  # succeeded | degraded | failed
    items: list[RetrievalResultItem] = Field(default_factory=list)
    total: int = 0
    latency_ms: float = 0.0
    filters_applied: dict = Field(default_factory=dict)
    error: str | None = None
