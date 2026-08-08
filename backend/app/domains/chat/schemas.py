"""HTTP contracts for the Chat domain."""

from __future__ import annotations

from datetime import datetime

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

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("content cannot be empty")
        return value


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
    citations: list[ChatMessageEvidenceRead] = Field(default_factory=list)
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
