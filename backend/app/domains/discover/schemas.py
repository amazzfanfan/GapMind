"""Strict API contracts for the asynchronous Discover workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.domains.agent.schemas import AgentStepRead


class DiscoverInput(BaseModel):
    topic: str | None = Field(default=None, max_length=4000)
    claim_item_id: str | None = None
    paper_ids: list[str] = Field(default_factory=list, max_length=200)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    constraints: str | None = Field(default=None, max_length=4000)


class DiscoverScope(BaseModel):
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    year_to: int | None = Field(default=None, ge=1900, le=2100)
    open_access_preferred: bool = False

    @model_validator(mode="after")
    def valid_years(self) -> "DiscoverScope":
        if self.year_from is not None and self.year_to is not None and self.year_from > self.year_to:
            raise ValueError("year_from must be <= year_to")
        return self


class DiscoverConfig(BaseModel):
    max_opportunities: int = Field(default=3, ge=1, le=5)
    top_k: int = Field(default=10, ge=1, le=30)
    include_counter_evidence: bool = True
    use_reranker: bool = True
    use_judge: bool = True


class DiscoverRunCreateRequest(BaseModel):
    input: DiscoverInput
    scope: DiscoverScope = Field(default_factory=DiscoverScope)
    config: DiscoverConfig = Field(default_factory=DiscoverConfig)

    @model_validator(mode="after")
    def require_input(self) -> "DiscoverRunCreateRequest":
        if not (self.input.topic and self.input.topic.strip()) and not self.input.claim_item_id:
            raise ValueError("input.topic or input.claim_item_id is required")
        return self


class DiscoverRunCreateResponse(BaseModel):
    run_id: str
    task_id: str | None = None
    status: str


class DiscoverExternalCandidateRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    discover_run_id: str
    query: str
    rank: int
    external_paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    abstract: str | None = None
    open_access_pdf: dict[str, Any] | None = None
    role: str
    role_confidence: float
    evidence_level: str
    verification_status: str
    imported_paper_id: str | None = None
    snapshot_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class DiscoverRunRead(BaseModel):
    model_config = {"from_attributes": True, "protected_namespaces": ()}

    id: str
    workspace_id: str
    task_id: str | None = None
    parent_run_id: str | None = None
    trigger_type: str
    input_topic: str | None = None
    input_claim_item_id: str | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    scope: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    status: str
    stage: str
    progress: float
    verification_status: str
    retrieval_snapshot_version: str
    prompt_version: str
    model_provider: str | None = None
    model_name: str | None = None
    model_parameters: dict[str, Any] = Field(default_factory=dict)
    corpus_version: str
    stage_summaries: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DiscoverRunDetail(DiscoverRunRead):
    external_candidates: list[DiscoverExternalCandidateRead] = Field(default_factory=list)
    opportunities: list["ResearchOpportunityRead"] = Field(default_factory=list)
    agent_steps: list[AgentStepRead] = Field(default_factory=list)


class ResearchOpportunityRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    workspace_id: str
    claim_item_id: str | None = None
    discover_run_id: str | None = None
    current_version_id: str | None = None
    title: str
    summary: str
    rationale: str
    suggested_directions: list[str] = Field(default_factory=list)
    confidence: float
    status: str
    source_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class OpportunityVersionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    opportunity_id: str
    version_number: int
    title: str
    problem_statement: str
    research_scope: str
    why_existing_work_is_insufficient: str
    candidate_research_question: str
    candidate_hypothesis: str
    candidate_validation_plan: dict[str, Any] = Field(default_factory=dict)
    open_risks: list[str] = Field(default_factory=list)
    novelty_score: float
    feasibility_score: float
    significance_score: float
    confidence: float
    evidence_coverage: float
    verification_status: str
    synthesis_metadata: dict[str, Any] = Field(default_factory=dict)
    created_by: str
    created_at: datetime


class OpportunityEvidenceRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    opportunity_version_id: str
    relation: str
    source_scope: str
    evidence_level: str
    paper_id: str | None = None
    external_candidate_id: str | None = None
    evidence_span_id: str | None = None
    artifact_id: str | None = None
    chunk_id: str | None = None
    rank: int | None = None
    score: float
    judgement: str
    judgement_confidence: float
    display_excerpt: str
    snapshot_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class OpportunityEvidenceContext(BaseModel):
    evidence: OpportunityEvidenceRead
    available: bool
    paper_id: str | None = None
    artifact_id: str | None = None
    artifact_kind: str | None = None
    filename: str | None = None
    content: str | None = None
    start_char: int | None = None
    end_char: int | None = None
    message: str | None = None


class HumanDecisionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    opportunity_id: str
    from_version_id: str
    to_version_id: str
    action: str
    reason: str | None = None
    defer_condition: str | None = None
    actor: str
    created_at: datetime


class ResearchPlanRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    workspace_id: str
    opportunity_id: str | None = None
    opportunity_version_id: str | None = None
    agent_run_id: str | None = None
    source_type: str = "opportunity"
    status: str
    research_question: str
    hypothesis: str
    scope_and_assumptions: str
    datasets: list[str] = Field(default_factory=list)
    baselines: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    validation_steps: list[str] = Field(default_factory=list)
    expected_supporting_result: str
    falsification_criteria: str
    risks: list[str] = Field(default_factory=list)
    resource_constraints: str
    created_at: datetime
    updated_at: datetime


class OpportunityDetail(BaseModel):
    opportunity: ResearchOpportunityRead
    current_version: OpportunityVersionRead | None = None
    versions: list[OpportunityVersionRead] = Field(default_factory=list)
    evidence: list[OpportunityEvidenceRead] = Field(default_factory=list)
    decisions: list[HumanDecisionRead] = Field(default_factory=list)
    plan: ResearchPlanRead | None = None


class OpportunityListResponse(BaseModel):
    items: list[ResearchOpportunityRead]
    total: int
    limit: int
    offset: int


class OpportunityPortfolioItem(BaseModel):
    opportunity: ResearchOpportunityRead
    current_version: OpportunityVersionRead | None = None
    plan: ResearchPlanRead | None = None


class OpportunityPortfolioResponse(BaseModel):
    items: list[OpportunityPortfolioItem]
    total: int
    limit: int
    offset: int


class ResearchPlanListResponse(BaseModel):
    items: list[ResearchPlanRead]
    total: int
    limit: int
    offset: int


class DiscoverRunListResponse(BaseModel):
    """Standard list envelope for ``GET /discover/runs``.

    Defined explicitly so the front-end's OpenAPI codegen produces a
    stable shape and so the endpoint can declare ``response_model=...``
    instead of returning a hand-written dict.
    """
    items: list["DiscoverRunRead"]
    total: int
    limit: int
    offset: int


DiscoverRunListResponse.model_rebuild()


class ExternalSelectionRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=30)
    action: Literal["import_and_verify"] = "import_and_verify"


class ConfirmRequest(BaseModel):
    version_id: str | None = None
    note: str | None = Field(default=None, max_length=2000)


class EditConfirmRequest(BaseModel):
    base_version_id: str
    changes: dict[str, Any] = Field(default_factory=dict)
    note: str | None = Field(default=None, max_length=2000)


class DecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
    defer_condition: str | None = Field(default=None, max_length=2000)


class ResearchOpportunityListResponse(OpportunityListResponse):
    """Backward-compatible alias used by the prototype endpoint."""


class PlanCreateResponse(BaseModel):
    plan: ResearchPlanRead
