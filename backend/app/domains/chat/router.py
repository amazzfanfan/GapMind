"""HTTP routes for the global AI chat."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
from app.domains.chat.service import (
    ChatConflictError,
    ChatConfigurationError,
    ChatInputError,
    ChatNotFoundError,
    ChatService,
    ChatUpstreamError,
)

router = APIRouter(prefix="/chat", tags=["chat"])


def _service(db: Session = Depends(get_db)) -> ChatService:
    return ChatService(db)


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail={"error": "chat_not_found", "message": str(exc)})


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=409, detail={"error": "chat_conflict", "message": str(exc)})


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
    try:
        return _send_response(service.send_new(payload.content))
    except ChatConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={"error": "deepseek_unavailable", "message": "AI 服务尚未配置，请联系管理员", "conversation_id": exc.conversation_id, "assistant_message_id": exc.assistant_message_id},
        ) from exc
    except ChatInputError as exc:
        raise HTTPException(status_code=400, detail={"error": "invalid_chat_input", "message": str(exc)}) from exc
    except ChatUpstreamError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": "deepseek_request_failed", "message": "AI 服务暂时不可用，请稍后重试", "conversation_id": exc.conversation_id, "assistant_message_id": exc.assistant_message_id},
        ) from exc


@router.get("/conversations/{conversation_id}", response_model=ChatConversationDetail)
def get_conversation(conversation_id: str, service: ChatService = Depends(_service)) -> ChatConversationDetail:
    try:
        conversation, messages = service.detail(conversation_id)
    except ChatNotFoundError as exc:
        raise _not_found(exc) from exc
    return ChatConversationDetail(
        conversation=ChatConversationRead.model_validate(conversation),
        messages=[ChatMessageRead.model_validate(item) for item in messages],
    )


@router.patch("/conversations/{conversation_id}", response_model=ChatConversationRead)
def rename_conversation(conversation_id: str, payload: ChatConversationUpdate, service: ChatService = Depends(_service)) -> ChatConversationRead:
    try:
        return ChatConversationRead.model_validate(service.rename(conversation_id, payload.title))
    except ChatNotFoundError as exc:
        raise _not_found(exc) from exc


@router.delete("/conversations/{conversation_id}", response_model=ChatDeleteResponse)
def delete_conversation(conversation_id: str, service: ChatService = Depends(_service)) -> ChatDeleteResponse:
    try:
        service.soft_delete(conversation_id)
    except ChatNotFoundError as exc:
        raise _not_found(exc) from exc
    return ChatDeleteResponse(id=conversation_id, deleted=True)


@router.post("/conversations/{conversation_id}/messages", response_model=ChatSendResponse)
def send_message(conversation_id: str, payload: ChatMessageCreate, service: ChatService = Depends(_service)) -> ChatSendResponse:
    try:
        return _send_response(service.send(conversation_id, payload.content))
    except ChatNotFoundError as exc:
        raise _not_found(exc) from exc
    except ChatConflictError as exc:
        raise _conflict(exc) from exc
    except ChatInputError as exc:
        raise HTTPException(status_code=400, detail={"error": "invalid_chat_input", "message": str(exc)}) from exc
    except ChatConfigurationError as exc:
        raise HTTPException(status_code=503, detail={"error": "deepseek_unavailable", "message": "AI 服务尚未配置，请联系管理员", "conversation_id": exc.conversation_id, "assistant_message_id": exc.assistant_message_id}) from exc
    except ChatUpstreamError as exc:
        raise HTTPException(status_code=502, detail={"error": "deepseek_request_failed", "message": "AI 服务暂时不可用，请稍后重试", "conversation_id": exc.conversation_id, "assistant_message_id": exc.assistant_message_id}) from exc


@router.post("/conversations/{conversation_id}/messages/{assistant_message_id}/retry", response_model=ChatSendResponse)
def retry_message(conversation_id: str, assistant_message_id: str, service: ChatService = Depends(_service)) -> ChatSendResponse:
    try:
        return _send_response(service.retry(conversation_id, assistant_message_id))
    except ChatNotFoundError as exc:
        raise _not_found(exc) from exc
    except ChatConflictError as exc:
        raise _conflict(exc) from exc
    except ChatConfigurationError as exc:
        raise HTTPException(status_code=503, detail={"error": "deepseek_unavailable", "message": "AI 服务尚未配置，请联系管理员", "conversation_id": exc.conversation_id, "assistant_message_id": exc.assistant_message_id}) from exc
    except ChatUpstreamError as exc:
        raise HTTPException(status_code=502, detail={"error": "deepseek_request_failed", "message": "AI 服务暂时不可用，请稍后重试", "conversation_id": exc.conversation_id, "assistant_message_id": exc.assistant_message_id}) from exc
