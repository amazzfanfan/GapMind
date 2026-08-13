"""HTTP routes for global and workspace-grounded AI chat.

Domain exceptions raised here are translated into HTTP responses by the
central handler registered in ``app.core.exception_handlers``. In
particular, ``ChatConfigurationError`` and ``ChatUpstreamError`` carry a
``conversation_id`` / ``assistant_message_id`` pair which the handler
exposes in the response envelope so the front-end can update message
status correctly.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.domains.chat.consistency import message_citation_check
from app.domains.chat.models import ChatMessage
from app.domains.chat.schemas import (
    ChatConversationCreate,
    ChatConversationDetail,
    ChatConversationListResponse,
    ChatConversationRead,
    ChatConversationUpdate,
    ChatDeleteResponse,
    ChatEvidenceContextRead,
    ChatMessageCreate,
    ChatMessageRead,
    ChatSendResponse,
    CitationCheckRead,
)
from app.domains.chat.service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


def _service(db: Session = Depends(get_db)) -> ChatService:
    return ChatService(db)


def _message_view(message: ChatMessage) -> ChatMessageRead:
    """Build the message DTO and validate its [En] citation markers."""
    read = ChatMessageRead.model_validate(message)
    if read.role == "assistant":
        ranks = [c.rank for c in read.citations if c.rank is not None]
        check = message_citation_check(
            read.content,
            ranks,
            grounded=read.grounding_status == "grounded",
        )
        read.citation_check = CitationCheckRead(
            referenced=check.referenced,
            broken=check.broken,
            ok=check.ok,
            grounded_without_citations=check.grounded_without_citations,
        )
    return read


def _send_response(result: tuple) -> ChatSendResponse:
    conversation, user_message, assistant_message = result
    return ChatSendResponse(
        conversation=ChatConversationRead.model_validate(conversation),
        user_message=_message_view(user_message),
        assistant_message=_message_view(assistant_message),
    )


@router.get("/conversations", response_model=ChatConversationListResponse)
def list_conversations(
    query: str | None = Query(None),
    workspace_id: str | None = Query(None),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: ChatService = Depends(_service),
) -> ChatConversationListResponse:
    items, total = service.list_conversations(query, limit, offset, workspace_id)
    return ChatConversationListResponse(
        items=[ChatConversationRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/conversations", response_model=ChatConversationRead, status_code=status.HTTP_201_CREATED)
def create_conversation(payload: ChatConversationCreate, service: ChatService = Depends(_service)) -> ChatConversationRead:
    return ChatConversationRead.model_validate(
        service.create_conversation(payload.title, payload.workspace_id)
    )


@router.post("/conversations/send", response_model=ChatSendResponse)
def send_new(payload: ChatMessageCreate, service: ChatService = Depends(_service)) -> ChatSendResponse:
    return _send_response(service.send_new(payload.content, payload.workspace_id))


@router.get("/conversations/{conversation_id}", response_model=ChatConversationDetail)
def get_conversation(conversation_id: str, service: ChatService = Depends(_service)) -> ChatConversationDetail:
    conversation, messages = service.detail(conversation_id)
    return ChatConversationDetail(
        conversation=ChatConversationRead.model_validate(conversation),
        messages=[_message_view(item) for item in messages],
    )


@router.patch("/conversations/{conversation_id}", response_model=ChatConversationRead)
def rename_conversation(conversation_id: str, payload: ChatConversationUpdate, service: ChatService = Depends(_service)) -> ChatConversationRead:
    return ChatConversationRead.model_validate(service.rename(conversation_id, payload.title))


@router.delete("/conversations/{conversation_id}", response_model=ChatDeleteResponse)
def delete_conversation(conversation_id: str, service: ChatService = Depends(_service)) -> ChatDeleteResponse:
    service.soft_delete(conversation_id)
    return ChatDeleteResponse(id=conversation_id, deleted=True)




@router.post("/conversations/{conversation_id}/messages/stream")
def stream_message(
    conversation_id: str,
    payload: ChatMessageCreate,
    service: ChatService = Depends(_service),
) -> StreamingResponse:
    """Stream a chat completion as Server-Sent Events (P0.5-1).

    Events are ``data: {json}`` lines: ``start`` (ids), ``evidence`` (retrieval
    citations), ``token`` (one delta each), ``done`` (final content), or
    ``error``. The full persisted message is available via GET afterwards.
    """
    def event_stream():
        for event in service.stream_send(
            conversation_id, payload.content, workspace_id=payload.workspace_id
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")
@router.post("/conversations/{conversation_id}/messages", response_model=ChatSendResponse)
def send_message(conversation_id: str, payload: ChatMessageCreate, service: ChatService = Depends(_service)) -> ChatSendResponse:
    return _send_response(
        service.send(conversation_id, payload.content, payload.workspace_id)
    )


@router.post("/conversations/{conversation_id}/messages/{assistant_message_id}/retry", response_model=ChatSendResponse)
def retry_message(conversation_id: str, assistant_message_id: str, service: ChatService = Depends(_service)) -> ChatSendResponse:
    return _send_response(service.retry(conversation_id, assistant_message_id))


@router.get(
    "/conversations/{conversation_id}/messages/{message_id}/evidence/{evidence_id}/context",
    response_model=ChatEvidenceContextRead,
)
def get_evidence_context(
    conversation_id: str,
    message_id: str,
    evidence_id: str,
    service: ChatService = Depends(_service),
) -> ChatEvidenceContextRead:
    evidence, artifact, content, unavailable_message = service.evidence_context(
        conversation_id,
        message_id,
        evidence_id,
    )
    return ChatEvidenceContextRead(
        evidence=evidence,
        available=content is not None,
        artifact_kind=artifact.kind if artifact else None,
        filename=artifact.original_filename if artifact else None,
        content=content,
        message=unavailable_message,
    )
