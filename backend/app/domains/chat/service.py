"""Application service for ordinary and workspace-grounded conversations."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable, Generator

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domains.artifact.models import Artifact
from app.domains.artifact.service import ArtifactService
from app.domains.chat.models import ChatConversation, ChatMessage, ChatMessageEvidence
from app.domains.paper.models import Paper
from app.domains.retrieval.schemas import RetrievalResultItem
from app.domains.retrieval.service import find_chunk_record, semantic_search
from app.domains.workspace.models import Workspace
from app.domains.workspace.service import WorkspaceService
from app.gateway.llm import LLMGateway, get_llm_gateway

# A chat stream whose client disconnected mid-flight is marked failed by the
# finally-guard in _stream_complete; rows older than this threshold that are
# still "generating" are treated as dead leftovers (pre-guard rows).
STALE_GENERATING_SECONDS = 15 * 60


class ChatNotFoundError(LookupError):
    pass


class ChatConflictError(RuntimeError):
    pass


class ChatInputError(ValueError):
    pass


class ChatConfigurationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        conversation_id: str | None = None,
        assistant_message_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.conversation_id = conversation_id
        self.assistant_message_id = assistant_message_id


class ChatUpstreamError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        conversation_id: str | None = None,
        assistant_message_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.conversation_id = conversation_id
        self.assistant_message_id = assistant_message_id


class ChatRetrievalError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        conversation_id: str | None = None,
        assistant_message_id: str | None = None,
    ) -> None:
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

    def list_conversations(
        self,
        query: str | None,
        limit: int,
        offset: int,
        workspace_id: str | None = None,
    ) -> tuple[list[ChatConversation], int]:
        stmt = select(ChatConversation).where(ChatConversation.is_deleted.is_(False))
        if workspace_id:
            WorkspaceService(self.db).get(workspace_id)
            stmt = stmt.where(ChatConversation.workspace_id == workspace_id)
        if query and query.strip():
            stmt = stmt.where(ChatConversation.title.ilike(f"%{query.strip()}%"))
        total = int(self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        items = list(
            self.db.scalars(
                stmt.order_by(
                    ChatConversation.last_message_at.desc().nullslast(),
                    ChatConversation.updated_at.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        )
        return items, total

    def create_conversation(
        self,
        title: str | None = None,
        workspace_id: str | None = None,
    ) -> ChatConversation:
        if workspace_id:
            WorkspaceService(self.db).get(workspace_id)
        conversation = ChatConversation(
            title=(title or "新对话").strip() or "新对话",
            workspace_id=workspace_id,
        )
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

    def send_new(
        self,
        content: str,
        workspace_id: str | None = None,
    ) -> tuple[ChatConversation, ChatMessage, ChatMessage]:
        content = self._validate_content(content)
        if workspace_id:
            WorkspaceService(self.db).get(workspace_id)
        conversation = ChatConversation(
            title=make_conversation_title(content),
            workspace_id=workspace_id,
        )
        self.db.add(conversation)
        self.db.flush()
        user_message, assistant_message = self._create_pending_messages(conversation, content)
        self.db.commit()
        return self._complete(
            conversation.id,
            user_message.id,
            assistant_message.id,
            [{"role": "user", "content": content}],
        )

    def send(
        self,
        conversation_id: str,
        content: str,
        workspace_id: str | None = None,
    ) -> tuple[ChatConversation, ChatMessage, ChatMessage]:
        content = self._validate_content(content)
        conversation = self.get_conversation(conversation_id)
        if workspace_id is not None and workspace_id != conversation.workspace_id:
            raise ChatConflictError("conversation workspace cannot be changed")
        self._ensure_not_generating(conversation.id)
        existing = self._completed_messages(conversation.id)
        user_message, assistant_message = self._create_pending_messages(conversation, content)
        self.db.commit()
        context = self._build_context(existing, content)
        return self._complete(conversation.id, user_message.id, assistant_message.id, context)

    def retry(
        self, conversation_id: str, assistant_message_id: str
    ) -> tuple[ChatConversation, ChatMessage, ChatMessage]:
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
            self._build_context(
                [item for item in prior if item.id != user_message.id], user_message.content
            ),
        )

    def _create_pending_messages(
        self, conversation: ChatConversation, content: str
    ) -> tuple[ChatMessage, ChatMessage]:
        max_sequence = self.db.scalar(
            select(func.max(ChatMessage.sequence)).where(
                ChatMessage.conversation_id == conversation.id
            )
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
            select(ChatMessage)
            .where(
                ChatMessage.conversation_id == conversation_id,
                ChatMessage.role == "assistant",
                ChatMessage.status == "generating",
            )
            .limit(1)
        )
        if active is None:
            return
        # P0.5-1 hardening: a stream whose client vanished mid-flight can leave
        # a row stuck in "generating" (rows created before the finally-guard
        # existed stay stuck forever). Treat rows untouched for longer than
        # STALE_GENERATING_SECONDS as dead so the conversation is not bricked.
        stale_for = None
        if active.updated_at is not None:
            updated_at = active.updated_at
            if updated_at.tzinfo is None:  # SQLite tests return naive datetimes
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            stale_for = datetime.now(timezone.utc) - updated_at
        if stale_for is not None and stale_for.total_seconds() > STALE_GENERATING_SECONDS:
            self._mark_failed(active, "流式响应中断（超时自动恢复）")
            return
        raise ChatConflictError("a response is already being generated")

    def _completed_messages(self, conversation_id: str) -> list[ChatMessage]:
        return list(
            self.db.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.conversation_id == conversation_id,
                    ChatMessage.status == "completed",
                )
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

    def _complete(
        self, conversation_id: str, user_id: str, assistant_id: str, context: list[dict[str, str]]
    ) -> tuple[ChatConversation, ChatMessage, ChatMessage]:
        assistant = self.db.get(ChatMessage, assistant_id)
        conversation = self.db.get(ChatConversation, conversation_id)
        user_message = self.db.get(ChatMessage, user_id)
        try:
            evidence: list[ChatMessageEvidence] = []
            if conversation.workspace_id:
                context, evidence = self._workspace_context(
                    conversation,
                    user_message.content,
                    context,
                    assistant.id,
                )
                if not evidence:
                    return self._complete_without_evidence(
                        conversation,
                        user_message,
                        assistant,
                    )
            gateway = self.gateway or get_llm_gateway()
            if not getattr(gateway, "api_key", None):
                raise ChatConfigurationError("DeepSeek API key is not configured")
            response = gateway.chat_completion(context, temperature=0.2)
        except ChatConfigurationError as exc:
            self._mark_failed(assistant, str(exc))
            raise ChatConfigurationError(
                str(exc), conversation_id=conversation_id, assistant_message_id=assistant_id
            ) from exc
        except ChatRetrievalError:
            raise
        except Exception as exc:
            safe_error = _safe_error_message(exc)
            self._mark_failed(assistant, safe_error)
            raise ChatUpstreamError(
                "DeepSeek request failed",
                conversation_id=conversation_id,
                assistant_message_id=assistant_id,
            ) from exc

        assistant.status = "completed"
        assistant.content = response.content
        assistant.error_message = None
        assistant.model = response.model
        assistant.prompt_tokens = response.prompt_tokens
        assistant.completion_tokens = response.completion_tokens
        assistant.total_tokens = response.total_tokens
        assistant.grounding_status = "grounded" if conversation.workspace_id else "not_requested"
        if conversation.workspace_id:
            assistant.citations = evidence
        conversation.model = response.model
        conversation.last_message_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(conversation)
        self.db.refresh(assistant)
        return conversation, user_message, assistant


    # ------------------------------------------------------------ streaming (P0.5-1)
    def stream_send_new(
        self,
        content: str,
        workspace_id: str | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """Stream a new-conversation message. Yields event dicts (see _stream_complete)."""
        content = self._validate_content(content)
        if workspace_id:
            WorkspaceService(self.db).get(workspace_id)
        conversation = ChatConversation(
            title=make_conversation_title(content),
            workspace_id=workspace_id,
        )
        self.db.add(conversation)
        self.db.flush()
        user_message, assistant_message = self._create_pending_messages(conversation, content)
        self.db.commit()
        yield from self._stream_complete(
            conversation.id, user_message.id, assistant_message.id,
            [{"role": "user", "content": content}],
        )

    def stream_send(
        self,
        conversation_id: str,
        content: str,
        workspace_id: str | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """Stream a message into an existing conversation. Yields event dicts."""
        content = self._validate_content(content)
        conversation = self.get_conversation(conversation_id)
        if workspace_id is not None and workspace_id != conversation.workspace_id:
            raise ChatConflictError("conversation workspace cannot be changed")
        self._ensure_not_generating(conversation.id)
        existing = self._completed_messages(conversation.id)
        user_message, assistant_message = self._create_pending_messages(conversation, content)
        self.db.commit()
        context = self._build_context(existing, content)
        yield from self._stream_complete(conversation.id, user_message.id, assistant_message.id, context)

    def _stream_complete(
        self,
        conversation_id: str,
        user_id: str,
        assistant_id: str,
        context: list[dict[str, str]],
    ) -> Generator[dict[str, Any], None, None]:
        """Stream LLM tokens for a message, persisting on completion.

        Yields ``{"type": ...}`` events: ``start`` (ids), ``evidence`` (retrieval
        citations), ``token`` (one delta per event), ``done`` (final content), or
        ``error``. Structured-format callers keep using ``_complete``.
        """
        assistant = self.db.get(ChatMessage, assistant_id)
        conversation = self.db.get(ChatConversation, conversation_id)
        user_message = self.db.get(ChatMessage, user_id)
        evidence: list[ChatMessageEvidence] = []
        try:
            if conversation.workspace_id:
                context, evidence = self._workspace_context(
                    conversation, user_message.content, context, assistant.id
                )
            gateway = self.gateway or get_llm_gateway()
            if not getattr(gateway, "api_key", None):
                raise ChatConfigurationError("DeepSeek API key is not configured")
        except ChatConfigurationError as exc:
            self._mark_failed(assistant, str(exc))
            yield {"type": "error", "message": str(exc)}
            return
        except ChatRetrievalError:
            raise

        yield {"type": "start", "conversation_id": conversation_id, "assistant_message_id": assistant_id}
        interrupted = True
        try:
            if conversation.workspace_id and evidence:
                yield {
                    "type": "evidence",
                    "citations": [
                        {
                            "id": ev.id,
                            "paper_title": ev.paper_title,
                            "section": ev.section,
                            "excerpt": ev.excerpt,
                            "rank": ev.rank,
                        }
                        for ev in evidence
                    ],
                }
            chunks: list[str] = []
            try:
                for delta in gateway.stream_chat_completion(context, temperature=0.2):
                    chunks.append(delta)
                    yield {"type": "token", "content": delta}
            except Exception as exc:
                safe_error = _safe_error_message(exc)
                self._mark_failed(assistant, safe_error)
                yield {"type": "error", "message": safe_error}
                return

            content = "".join(chunks)
            assistant.status = "completed"
            assistant.content = content
            assistant.error_message = None
            assistant.grounding_status = "grounded" if conversation.workspace_id else "not_requested"
            if conversation.workspace_id:
                assistant.citations = evidence
            conversation.last_message_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(assistant)
            interrupted = False
            yield {"type": "done", "content": content}
        finally:
            # P0.5-1 hardening: a client disconnect mid-stream raises
            # GeneratorExit at a yield point; without this guard the row stays
            # "generating" forever and blocks the whole conversation.
            if interrupted and assistant.status == "generating":
                try:
                    self._mark_failed(assistant, "流式响应中断：客户端提前断开")
                except Exception:
                    self.db.rollback()

    def _workspace_context(
        self,
        conversation: ChatConversation,
        question: str,
        context: list[dict[str, str]],
        assistant_id: str,
    ) -> tuple[list[dict[str, str]], list[ChatMessageEvidence]]:
        workspace = WorkspaceService(self.db).get(conversation.workspace_id)
        result = semantic_search(
            workspace_id=workspace.id,
            query=question,
            top_k=settings.chat_rag_top_k,
            use_reranker=True,
        )
        if result.status == "failed":
            assistant = self.db.get(ChatMessage, assistant_id)
            self._mark_failed(
                assistant,
                result.error or "Workspace retrieval failed",
                grounding_status="retrieval_failed",
            )
            raise ChatRetrievalError(
                "工作区论文检索失败，请检查向量化服务与 Milvus 后重试",
                conversation_id=conversation.id,
                assistant_message_id=assistant_id,
            )

        evidence = self._materialize_evidence(
            workspace,
            assistant_id,
            result.items,
        )
        if not evidence:
            return context, []

        profile = self._workspace_profile(workspace)
        evidence_text = self._evidence_prompt(evidence)
        system_message = {
            "role": "system",
            "content": (
                "你是 GapMind 的课题空间研究助手。只能依据下方工作区资料回答与该课题相关的事实性问题。"
                "回答中的关键结论必须使用 [E1]、[E2] 形式引用证据；不要编造不存在的论文、实验结果或引用。"
                "如果证据不足，请直接说明不足，并指出还需要什么资料。可以使用对话历史理解代词和上下文，"
                "但历史中的助手回答不能替代论文证据。\n\n"
                f"工作区资料：\n{profile}\n\n检索证据：\n{evidence_text}"
            ),
        }
        return [system_message, *context], evidence

    def _materialize_evidence(
        self,
        workspace: Workspace,
        assistant_id: str,
        items: list[RetrievalResultItem],
    ) -> list[ChatMessageEvidence]:
        evidence: list[ChatMessageEvidence] = []
        for rank, item in enumerate(items, 1):
            if not item.paper_id:
                continue
            paper = self.db.get(Paper, item.paper_id)
            if paper is None or paper.is_deleted or paper.workspace_id != workspace.id:
                continue
            chunk = (
                find_chunk_record(workspace.id, paper.id, item.chunk_id) if item.chunk_id else None
            )
            artifact_id = chunk.source_artifact_id if chunk else item.artifact_id
            artifact = self.db.get(Artifact, artifact_id) if artifact_id else None
            if artifact is not None and (
                artifact.is_deleted or artifact.workspace_id != workspace.id
            ):
                artifact_id = None
            excerpt = self._postgres_safe_text(item.text).strip()[:4000]
            if not excerpt:
                continue
            evidence.append(
                ChatMessageEvidence(
                    message_id=assistant_id,
                    workspace_id=workspace.id,
                    paper_id=paper.id,
                    artifact_id=artifact_id,
                    chunk_id=self._postgres_safe_text(item.chunk_id) or None,
                    paper_title=self._postgres_safe_text(paper.title) or None,
                    section=self._postgres_safe_text(item.section) or None,
                    excerpt=excerpt,
                    start_char=chunk.start_char if chunk else None,
                    end_char=chunk.end_char if chunk else None,
                    score=float(item.score),
                    rank=rank,
                )
            )
        return evidence

    @staticmethod
    def _postgres_safe_text(value: object | None) -> str:
        """Remove NUL bytes that PostgreSQL rejects in text and JSON values.

        PDF extraction can preserve embedded ``0x00`` characters inside an
        otherwise valid chunk.  They are not meaningful prose, so removing
        them at the persistence boundary keeps evidence offsets and source
        artifacts auditable while preventing an entire Agent run from failing.
        """

        return str(value or "").replace("\x00", "")

    @staticmethod
    def _workspace_profile(workspace: Workspace) -> str:
        fields = [f"名称：{workspace.name}"]
        if workspace.topic:
            fields.append(f"主题：{workspace.topic}")
        if workspace.keywords:
            fields.append(f"关键词：{', '.join(workspace.keywords)}")
        if workspace.goals:
            fields.append(f"目标：{workspace.goals}")
        if workspace.constraints:
            fields.append(f"约束：{workspace.constraints}")
        return "\n".join(fields)

    @staticmethod
    def _evidence_prompt(evidence: list[ChatMessageEvidence]) -> str:
        blocks: list[str] = []
        total_chars = 0
        for item in evidence:
            block = (
                f"[E{item.rank}] 论文：{item.paper_title or '未命名论文'}；"
                f"章节：{item.section or '未知'}；相关度：{item.score:.3f}\n"
                f"{item.excerpt}"
            )
            remaining = settings.chat_rag_max_context_chars - total_chars
            if remaining <= 0:
                break
            blocks.append(block[:remaining])
            total_chars += min(len(block), remaining)
        return "\n\n".join(blocks)

    def _complete_without_evidence(
        self,
        conversation: ChatConversation,
        user_message: ChatMessage,
        assistant: ChatMessage,
    ) -> tuple[ChatConversation, ChatMessage, ChatMessage]:
        assistant.status = "completed"
        assistant.content = (
            "当前工作区没有检索到可用于回答这个问题的已索引论文内容。"
            "请先确认论文 PDF 已完成解析和向量化，或者换一个更具体的问题后重试。"
        )
        assistant.error_message = None
        assistant.grounding_status = "no_evidence"
        conversation.last_message_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(conversation)
        self.db.refresh(assistant)
        return conversation, user_message, assistant

    def evidence_context(
        self,
        conversation_id: str,
        message_id: str,
        evidence_id: str,
    ) -> tuple[ChatMessageEvidence, Artifact | None, str | None, str | None]:
        conversation = self.get_conversation(conversation_id)
        evidence = self.db.scalar(
            select(ChatMessageEvidence)
            .join(ChatMessage, ChatMessage.id == ChatMessageEvidence.message_id)
            .where(
                ChatMessageEvidence.id == evidence_id,
                ChatMessageEvidence.message_id == message_id,
                ChatMessageEvidence.workspace_id == conversation.workspace_id,
                ChatMessage.conversation_id == conversation.id,
            )
        )
        if evidence is None:
            raise ChatNotFoundError("chat evidence not found")
        if not evidence.artifact_id:
            return evidence, None, None, "证据没有可定位的原文文件"
        artifact = self.db.get(Artifact, evidence.artifact_id)
        if (
            artifact is None
            or artifact.is_deleted
            or artifact.workspace_id != evidence.workspace_id
        ):
            return evidence, None, None, "证据原文文件已不可用"
        path = ArtifactService(self.db).resolve_abs_path(artifact)
        if not path.exists():
            return evidence, artifact, None, "证据原文文件不存在"
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return evidence, artifact, None, "证据原文读取失败"
        return evidence, artifact, content, None

    def _mark_failed(
        self,
        assistant: ChatMessage,
        error_message: str,
        *,
        grounding_status: str | None = None,
    ) -> None:
        assistant.status = "failed"
        assistant.error_message = error_message[:1000]
        if grounding_status:
            assistant.grounding_status = grounding_status
        conversation = self.db.get(ChatConversation, assistant.conversation_id)
        conversation.last_message_at = datetime.now(timezone.utc)
        self.db.commit()


def _safe_error_message(exc: Exception) -> str:
    raw = f"{type(exc).__name__}: {exc}"
    raw = re.sub(r"(?i)(api[-_ ]?key|authorization|bearer)\s*[:=]?\s*\S+", r"\1: [redacted]", raw)
    raw = re.sub(r"(?i)sk-[a-z0-9_-]+", "[redacted]", raw)
    return raw[:1000]
