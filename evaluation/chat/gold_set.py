"""Schemas for the offline Workspace Chat QA benchmark.

The retrieval gate answers whether a paper can be recalled.  This benchmark
starts one layer later: given a saved Chat response, did it use real paper
markers, keep plan/report/code sources distinct, and reach the human-annotated
answerability verdict?  It deliberately does not execute an LLM or mutate a
workspace, so the evaluation data remains reviewable and reproducible.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from evaluation.retrieval.gold_set import Freeze


ExpectedVerdict = Literal["supported", "insufficient_evidence"]
HumanVerdict = Literal["supported", "insufficient_evidence", "unsupported"]
RetrievalAuditStatus = Literal["succeeded", "degraded", "failed", "unknown"]
RerankerAuditStatus = Literal[
    "applied",
    "enabled_no_rerank",
    "degraded",
    "disabled",
    "unknown",
]


class ChatContext(BaseModel):
    """Explicit non-paper context required before replaying one question."""

    mode: Literal["workspace_papers", "workspace_with_confirmed_plan"] = "workspace_papers"
    research_plan_ref: str | None = Field(
        default=None,
        description="Human-readable confirmed plan title or local id; never a paper reference.",
    )

    @model_validator(mode="after")
    def _plan_context_requires_ref(self) -> "ChatContext":
        if self.mode == "workspace_with_confirmed_plan" and not self.research_plan_ref:
            raise ValueError("workspace_with_confirmed_plan requires research_plan_ref")
        return self


class ChatQAQuestion(BaseModel):
    """One human-annotated question and its expected evidence contract."""

    query_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=3, max_length=2000)
    expected_verdict: ExpectedVerdict
    required_paper_refs: list[str] = Field(default_factory=list, max_length=10)
    context: ChatContext = Field(default_factory=ChatContext)
    note: str | None = None

    @model_validator(mode="after")
    def _validate_evidence_contract(self) -> "ChatQAQuestion":
        refs = [ref.strip() for ref in self.required_paper_refs if ref.strip()]
        if len(refs) != len(set(ref.casefold() for ref in refs)):
            raise ValueError("required_paper_refs must not contain duplicates")
        if self.expected_verdict == "supported" and not refs:
            raise ValueError("supported questions require at least one required_paper_ref")
        if self.expected_verdict == "insufficient_evidence" and refs:
            raise ValueError("insufficient_evidence questions must not declare required_paper_refs")
        self.required_paper_refs = refs
        return self


class ChatQAGoldSet(BaseModel):
    """Frozen, human-authored expectations for one workspace corpus."""

    schema_version: str = "1.0.0"
    case_id: str = Field(min_length=1, max_length=128)
    corpus_version: str = Field(min_length=1, max_length=255)
    annotation_status: Literal["draft", "gold"] = "draft"
    freeze: Freeze = Field(default_factory=Freeze)
    workspace_hint: str | None = None
    questions: list[ChatQAQuestion] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _unique_query_ids(self) -> "ChatQAGoldSet":
        query_ids = [question.query_id for question in self.questions]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("questions must use unique query_id values")
        return self


class EvidenceSnapshot(BaseModel):
    """The persisted paper evidence needed to validate one ``[En]`` marker."""

    rank: int = Field(ge=1)
    paper_ref: str = Field(min_length=1)


class SourceSnapshot(BaseModel):
    """A non-paper source copied from ChatMessage.source_manifest."""

    marker: str = Field(pattern=r"^[PDC][1-9][0-9]*$")
    source_type: Literal["plan", "report", "code_draft"]
    title: str = Field(min_length=1)


class RetrievalAuditSnapshot(BaseModel):
    """An anonymized, non-authoritative snapshot of one retrieval run.

    Request ids are deliberately omitted: the QA snapshot is for measuring
    retrieval coverage and latency, not for tracing a local database row.
    These fields never decide whether an answer is factually supported.
    """

    status: RetrievalAuditStatus = "unknown"
    diagnostic_code: str | None = None
    recall_count: int | None = Field(default=None, ge=0)
    returned_chunk_count: int = Field(default=0, ge=0)
    final_paper_count: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0)
    reranker_status: RerankerAuditStatus = "unknown"


class ChatQAObservation(BaseModel):
    """One saved Chat answer exported for an offline QA evaluation."""

    query_id: str = Field(min_length=1, max_length=128)
    message_id: str | None = None
    answer_text: str = Field(min_length=1)
    grounding_status: str = Field(min_length=1)
    evidence: list[EvidenceSnapshot] = Field(default_factory=list, max_length=20)
    sources: list[SourceSnapshot] = Field(default_factory=list, max_length=10)
    retrieval_audit: RetrievalAuditSnapshot | None = None
    human_verdict: HumanVerdict | None = None

    @model_validator(mode="after")
    def _unique_snapshot_markers(self) -> "ChatQAObservation":
        evidence_ranks = [item.rank for item in self.evidence]
        source_markers = [item.marker for item in self.sources]
        if len(evidence_ranks) != len(set(evidence_ranks)):
            raise ValueError("evidence ranks must be unique")
        if len(source_markers) != len(set(source_markers)):
            raise ValueError("source markers must be unique")
        return self


class ChatQAObservationSet(BaseModel):
    """Answers observed for exactly one Chat QA gold case."""

    gold_case_id: str = Field(min_length=1, max_length=128)
    observations: list[ChatQAObservation] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _unique_query_ids(self) -> "ChatQAObservationSet":
        query_ids = [item.query_id for item in self.observations]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("observations must use unique query_id values")
        return self


__all__ = [
    "ChatContext",
    "ChatQAGoldSet",
    "ChatQAObservation",
    "ChatQAObservationSet",
    "ChatQAQuestion",
    "EvidenceSnapshot",
    "HumanVerdict",
    "RetrievalAuditSnapshot",
    "RetrievalAuditStatus",
    "RerankerAuditStatus",
    "SourceSnapshot",
]
