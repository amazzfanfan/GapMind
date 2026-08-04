"""HTTP routes for the global AI chat.

Domain exceptions raised here are translated into HTTP responses by the
central handler registered in ``app.core.exception_handlers``. In
particular, ``ChatConfigurationError`` and ``ChatUpstreamError`` carry a
``conversation_id`` / ``assistant_message_id`` pair which the handler
exposes in the response envelope so the front-end can update message
status correctly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.domains.chat.schemas import (
    ChatConversationCreate,
    ChatConversationDetail,
    ChatConversationListResponse,
    ChatConversationRead,
    ChatConversationUpdate,
    ChatDeleteResponse,
    ChatMessageCreate,
    ChatMessageRead,
    ChatSendResponse,
)
from app.domains.chat.service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


def _service(db: Session = Depends(get_db)) -> ChatService:
    return ChatService(db)


def _send_response(result: tuple) -> ChatSendResponse:
    conversation, user_message, assistant_message = result
    return ChatSendResponse(
        conversation=ChatConversationRead.model_validate(conversation),
        user_message=ChatMessageRead.model_validate(user_message),
        assistant_message=ChatMessageRead.model_validate(assistant_message),
    )


@router.get("/conversations", response_model=ChatConversationListResponse)
def list_conversations(
    query: str | None = Query(None),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: ChatService = Depends(_service),
) -> ChatConversationListResponse:
    items, total = service.list_conversations(query, limit, offset)
    return ChatConversationListResponse(
        items=[ChatConversationRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/conversations", response_model=ChatConversationRead, status_code=status.HTTP_201_CREATED)
def create_conversation(payload: ChatConversationCreate, service: ChatService = Depends(_service)) -> ChatConversationRead:
    return ChatConversationRead.model_validate(service.create_conversation(payload.title))


@router.post("/conversations/send", response_model=ChatSendResponse)
def send_new(payload: ChatMessageCreate, service: ChatService = Depends(_service)) -> ChatSendResponse:
    return _send_response(service.send_new(payload.content))


@router.get("/conversations/{conversation_id}", response_model=ChatConversationDetail)
def get_conversation(conversation_id: str, service: ChatService = Depends(_service)) -> ChatConversationDetail:
    conversation, messages = service.detail(conversation_id)
    return ChatConversationDetail(
        conversation=ChatConversationRead.model_validate(conversation),
        messages=[ChatMessageRead.model_validate(item) for item in messages],
    )


@router.patch("/conversations/{conversation_id}", response_model=ChatConversationRead)
def rename_conversation(conversation_id: str, payload: ChatConversationUpdate, service: ChatService = Depends(_service)) -> ChatConversationRead:
    return ChatConversationRead.model_validate(service.rename(conversation_id, payload.title))


@router.delete("/conversations/{conversation_id}", response_model=ChatDeleteResponse)
def delete_conversation(conversation_id: str, service: ChatService = Depends(_service)) -> ChatDeleteResponse:
    service.soft_delete(conversation_id)
    return ChatDeleteResponse(id=conversation_id, deleted=True)


@router.post("/conversations/{conversation_id}/messages", response_model=ChatSendResponse)
def send_message(conversation_id: str, payload: ChatMessageCreate, service: ChatService = Depends(_service)) -> ChatSendResponse:
    return _send_response(service.send(conversation_id, payload.content))


@router.post("/conversations/{conversation_id}/messages/{assistant_message_id}/retry", response_model=ChatSendResponse)
def retry_message(conversation_id: str, assistant_message_id: str, service: ChatService = Depends(_service)) -> ChatSendResponse:
    return _send_response(service.retry(conversation_id, assistant_message_id))