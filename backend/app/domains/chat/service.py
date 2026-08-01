"""Application service for ordinary DeepSeek conversations.

Chat intentionally has no workspace, retrieval, Discover, or tool context.
The service owns persistence and delegates the upstream call to the existing
LLMGateway so API credentials stay on the backend.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domains.chat.models import ChatConversation, ChatMessage
from app.gateway.llm import LLMGateway, get_llm_gateway


class ChatNotFoundError(LookupError):
    pass


class ChatConflictError(RuntimeError):
    pass


class ChatInputError(ValueError):
    pass


class ChatConfigurationError(RuntimeError):
    def __init__(self, message: str, *, conversation_id: str | None = None, assistant_message_id: str | None = None) -> None:
        super().__init__(message)
        self.conversation_id = conversation_id
        self.assistant_message_id = assistant_message_id


class ChatUpstreamError(RuntimeError):
    def __init__(self, message: str, *, conversation_id: str | None = None, assistant_message_id: str | None = None) -> None:
        super().__init__(message)
        self.conversation_id = conversation_id
        self.assistant_message_id = assistant_message_id


def make_conversation_title(content: str) -> str:
    """Create a deterministic title without spending another LLM request."""
    normalized = re.sub(r"\s+", " ", content).strip()
    if not normalized:
        return "新对话"
    return normalized[:38] + ("…" if len(normalized) > 38 else "")


class ChatService:
    def __init__(self, db: Session, gateway: LLMGateway | None = None) -> None:
        self.db = db
        self.gateway = gateway

    def list_conversations(self, query: str | None, limit: int, offset: int) -> tuple[list[ChatConversation], int]:
        stmt = select(ChatConversation).where(ChatConversation.is_deleted.is_(False))
        if query and query.strip():
            stmt = stmt.where(ChatConversation.title.ilike(f"%{query.strip()}%"))
        total = int(self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        items = list(
            self.db.scalars(
                stmt.order_by(
                    ChatConversation.last_message_at.desc().nullslast(),
                    ChatConversation.updated_at.desc(),
                ).offset(offset).limit(limit)
            )
        )
        return items, total

    def create_conversation(self, title: str | None = None) -> ChatConversation:
        conversation = ChatConversation(title=(title or "新对话").strip() or "新对话")
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def get_conversation(self, conversation_id: str) -> ChatConversation:
        conversation = self.db.scalar(
            select(ChatConversation).where(
                ChatConversation.id == conversation_id,
                ChatConversation.is_deleted.is_(False),
            )
        )
        if conversation is None:
            raise ChatNotFoundError("conversation not found")
        return conversation

    def detail(self, conversation_id: str) -> tuple[ChatConversation, list[ChatMessage]]:
        conversation = self.get_conversation(conversation_id)
        messages = list(
            self.db.scalars(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation.id)
                .order_by(ChatMessage.sequence.asc())
            )
        )
        return conversation, messages

    def rename(self, conversation_id: str, title: str) -> ChatConversation:
        conversation = self.get_conversation(conversation_id)
        conversation.title = title.strip()
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def soft_delete(self, conversation_id: str) -> None:
        conversation = self.get_conversation(conversation_id)
        conversation.is_deleted = True
        self.db.commit()

    def send_new(self, content: str) -> tuple[ChatConversation, ChatMessage, ChatMessage]:
        content = self._validate_content(content)
        conversation = ChatConversation(title=make_conversation_title(content))
        self.db.add(conversation)
        self.db.flush()
        user_message, assistant_message = self._create_pending_messages(conversation, content)
        self.db.commit()
        return self._complete(conversation.id, user_message.id, assistant_message.id, [{"role": "user", "content": content}])

    def send(self, conversation_id: str, content: str) -> tuple[ChatConversation, ChatMessage, ChatMessage]:
        content = self._validate_content(content)
        conversation = self.get_conversation(conversation_id)
        self._ensure_not_generating(conversation.id)
        existing = self._completed_messages(conversation.id)
        user_message, assistant_message = self._create_pending_messages(conversation, content)
        self.db.commit()
        context = self._build_context(existing, content)
        return self._complete(conversation.id, user_message.id, assistant_message.id, context)

    def retry(self, conversation_id: str, assistant_message_id: str) -> tuple[ChatConversation, ChatMessage, ChatMessage]:
        conversation = self.get_conversation(conversation_id)
        assistant = self.db.scalar(
            select(ChatMessage).where(
                ChatMessage.id == assistant_message_id,
                ChatMessage.conversation_id == conversation.id,
            )
        )
        if assistant is None or assistant.role != "assistant":
            raise ChatNotFoundError("assistant message not found")
        if assistant.status != "failed":
            raise ChatConflictError("only failed assistant messages can be retried")
        self._ensure_not_generating(conversation.id)
        prior = list(
            self.db.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.conversation_id == conversation.id,
                    ChatMessage.sequence < assistant.sequence,
                    ChatMessage.status == "completed",
                )
                .order_by(ChatMessage.sequence.asc())
            )
        )
        user_message = next((item for item in reversed(prior) if item.role == "user"), None)
        if user_message is None:
            raise ChatConflictError("no user message is available for retry")
        assistant.status = "generating"
        assistant.error_message = None
        assistant.content = ""
        self.db.commit()
        return self._complete(
            conversation.id,
            user_message.id,
            assistant.id,
            self._build_context([item for item in prior if item.id != user_message.id], user_message.content),
        )

    def _create_pending_messages(self, conversation: ChatConversation, content: str) -> tuple[ChatMessage, ChatMessage]:
        max_sequence = self.db.scalar(
            select(func.max(ChatMessage.sequence)).where(ChatMessage.conversation_id == conversation.id)
        )
        sequence = int(max_sequence or 0) + 1
        user_message = ChatMessage(
            conversation_id=conversation.id,
            role="user",
            content=content,
            status="completed",
            sequence=sequence,
        )
        assistant_message = ChatMessage(
            conversation_id=conversation.id,
            role="assistant",
            content="",
            status="generating",
            sequence=sequence + 1,
        )
        self.db.add_all([user_message, assistant_message])
        return user_message, assistant_message

    @staticmethod
    def _validate_content(content: str) -> str:
        content = content.strip()
        if not content:
            raise ChatInputError("消息不能为空")
        if len(content) > settings.chat_max_input_chars:
            raise ChatInputError(f"消息长度不能超过 {settings.chat_max_input_chars} 个字符")
        return content

    def _ensure_not_generating(self, conversation_id: str) -> None:
        active = self.db.scalar(
            select(ChatMessage.id).where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.role == "assistant",
                ChatMessage.status == "generating",
            ).limit(1)
        )
        if active:
            raise ChatConflictError("a response is already being generated")

    def _completed_messages(self, conversation_id: str) -> list[ChatMessage]:
        return list(
            self.db.scalars(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conversation_id, ChatMessage.status == "completed")
                .order_by(ChatMessage.sequence.desc())
                .limit(settings.chat_history_message_limit)
            )
        )[::-1]

    def _build_context(self, messages: Iterable[ChatMessage], content: str) -> list[dict[str, str]]:
        context: list[dict[str, str]] = []
        total_chars = 0
        for message in messages:
            if message.role not in {"user", "assistant"} or message.status != "completed":
                continue
            if total_chars + len(message.content) > settings.chat_history_char_limit:
                break
            context.append({"role": message.role, "content": message.content})
            total_chars += len(message.content)
        context.append({"role": "user", "content": content})
        return context

    def _complete(self, conversation_id: str, user_id: str, assistant_id: str, context: list[dict[str, str]]) -> tuple[ChatConversation, ChatMessage, ChatMessage]:
        assistant = self.db.get(ChatMessage, assistant_id)
        try:
            gateway = self.gateway or get_llm_gateway()
            if not getattr(gateway, "api_key", None):
                raise ChatConfigurationError("DeepSeek API key is not configured")
            response = gateway.chat_completion(context, temperature=0.2)
        except ChatConfigurationError as exc:
            self._mark_failed(assistant, str(exc))
            raise ChatConfigurationError(str(exc), conversation_id=conversation_id, assistant_message_id=assistant_id) from exc
        except Exception as exc:
            safe_error = _safe_error_message(exc)
            self._mark_failed(assistant, safe_error)
            raise ChatUpstreamError("DeepSeek request failed", conversation_id=conversation_id, assistant_message_id=assistant_id) from exc

        assistant.status = "completed"
        assistant.content = response.content
        assistant.error_message = None
        assistant.model = response.model
        assistant.prompt_tokens = response.prompt_tokens
        assistant.completion_tokens = response.completion_tokens
        assistant.total_tokens = response.total_tokens
        conversation = self.db.get(ChatConversation, conversation_id)
        conversation.model = response.model
        conversation.last_message_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(conversation)
        self.db.refresh(assistant)
        user_message = self.db.get(ChatMessage, user_id)
        return conversation, user_message, assistant

    def _mark_failed(self, assistant: ChatMessage, error_message: str) -> None:
        assistant.status = "failed"
        assistant.error_message = error_message[:1000]
        conversation = self.db.get(ChatConversation, assistant.conversation_id)
        conversation.last_message_at = datetime.now(timezone.utc)
        self.db.commit()


def _safe_error_message(exc: Exception) -> str:
    raw = f"{type(exc).__name__}: {exc}"
    raw = re.sub(r"(?i)(api[-_ ]?key|authorization|bearer)\s*[:=]?\s*\S+", r"\1: [redacted]", raw)
    raw = re.sub(r"(?i)sk-[a-z0-9_-]+", "[redacted]", raw)
    return raw[:1000]
