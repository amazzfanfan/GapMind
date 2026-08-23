"""HTTP contracts for the Chat domain."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    workspace_id: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("title cannot be empty")
        return value


class ChatConversationUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("title cannot be empty")
        return value


class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=1)
    workspace_id: str | None = None
    research_plan_id: str | None = None
    source_artifact_ids: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content cannot be empty")
        return value

    @field_validator("source_artifact_ids")
    @classmethod
    def normalize_source_artifact_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item and item.strip()))


class ChatConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    workspace_id: str | None = None
    model: str | None = None
    last_message_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ChatMessageEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    message_id: str
    workspace_id: str
    paper_id: str | None = None
    artifact_id: str | None = None
    chunk_id: str | None = None
    paper_title: str | None = None
    section: str | None = None
    excerpt: str
    start_char: int | None = None
    end_char: int | None = None
    score: float
    rank: int
    created_at: datetime
    updated_at: datetime


class CitationCheckRead(BaseModel):
    """Result of validating [En] markers in an assistant message against its citations."""
    referenced: list[int] = Field(default_factory=list)
    broken: list[int] = Field(default_factory=list)
    ok: bool = True
    grounded_without_citations: bool = False


class SourceCheckRead(BaseModel):
    """Validation of [P1]/[D1]/[C1] markers against the source passport."""

    referenced: list[str] = Field(default_factory=list)
    broken: list[str] = Field(default_factory=list)
    ok: bool = True


class ChatMessageSourceRead(BaseModel):
    """One explicitly labelled context source used for an answer."""

    marker: str
    source_type: Literal["plan", "paper", "report", "code_draft"]
    source_id: str
    label: str
    title: str
    status: str
    detail: str | None = None


class ChatContextPlanOption(BaseModel):
    id: str
    title: str
    research_question: str
    status: str


class ChatContextArtifactOption(BaseModel):
    id: str
    plan_id: str
    source_type: Literal["report", "code_draft"]
    label: str
    title: str
    status: str


class ChatContextOptionsResponse(BaseModel):
    plans: list[ChatContextPlanOption] = Field(default_factory=list)
    artifacts: list[ChatContextArtifactOption] = Field(default_factory=list)


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: str
    content: str
    status: str
    error_message: str | None = None
    sequence: int
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    grounding_status: str = "not_requested"
    retrieval_diagnostic_code: str | None = None
    citations: list[ChatMessageEvidenceRead] = Field(default_factory=list)
    citation_check: CitationCheckRead | None = None
    sources: list[ChatMessageSourceRead] = Field(default_factory=list)
    source_check: SourceCheckRead | None = None
    created_at: datetime
    updated_at: datetime


class ChatConversationListResponse(BaseModel):
    items: list[ChatConversationRead]
    total: int
    limit: int
    offset: int


class ChatConversationDetail(BaseModel):
    conversation: ChatConversationRead
    messages: list[ChatMessageRead]


class ChatSendResponse(BaseModel):
    conversation: ChatConversationRead
    user_message: ChatMessageRead
    assistant_message: ChatMessageRead


class ChatDeleteResponse(BaseModel):
    id: str
    deleted: bool


class ChatEvidenceContextRead(BaseModel):
    evidence: ChatMessageEvidenceRead
    available: bool
    artifact_kind: str | None = None
    filename: str | None = None
    content: str | None = None
    message: str | None = None
