"""Knowledge service layer (Phase 3: read + write)."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.knowledge.models import (
    CanonicalEntity,
    EvidenceSpan,
    ExtractionRejection,
    ExtractionRun,
    KnowledgeItem,
    KnowledgeRelation,
)
from app.domains.knowledge.schemas import (
    EvidenceSpanCreate,
    ExtractionRejectionCreate,
    KnowledgeItemCreate,
    KnowledgeRelationCreate,
)

logger = get_logger(__name__)


class KnowledgeItemNotFoundError(Exception):
    def __init__(self, item_id: str) -> None:
        super().__init__(f"Knowledge item not found: {item_id}")
        self.item_id = item_id


class ExtractionRunNotFoundError(Exception):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"Extraction run not found: {run_id}")
        self.run_id = run_id


class KnowledgeService:
    """Knowledge queries + writes for Phase 3."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # -------------------------------------------------------- knowledge items
    def get_item(self, item_id: str) -> KnowledgeItem:
        self._validate_uuid(item_id)
        item = self.db.get(KnowledgeItem, item_id)
        if item is None or item.is_deleted:
            raise KnowledgeItemNotFoundError(item_id)
        return item

    def list_items(
        self,
        *,
        workspace_id: str,
        type_filter: str | None = None,
        status_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[KnowledgeItem], int]:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        q = select(KnowledgeItem).where(
            KnowledgeItem.workspace_id == workspace_id,
            KnowledgeItem.is_deleted.is_(False),
        )
        if type_filter:
            q = q.where(KnowledgeItem.type == type_filter)
        if status_filter:
            q = q.where(KnowledgeItem.status == status_filter)
        items_q = q.order_by(KnowledgeItem.created_at.desc()).limit(limit).offset(offset)
        total_q = select(func.count()).select_from(q.subquery())
        items = list(self.db.execute(items_q).scalars().all())
        total = int(self.db.execute(total_q).scalar() or 0)
        return items, total

    # -------------------------------------------------------- relations
    def list_relations(
        self,
        *,
        workspace_id: str,
        item_id: str | None = None,
        relation_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[KnowledgeRelation], int]:
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        q = select(KnowledgeRelation).where(
            KnowledgeRelation.workspace_id == workspace_id,
            KnowledgeRelation.is_deleted.is_(False),
        )
        if item_id:
            q = q.where(
                (KnowledgeRelation.source_id == item_id)
                | (KnowledgeRelation.target_id == item_id)
            )
        if relation_type:
            q = q.where(KnowledgeRelation.relation_type == relation_type)
        items_q = q.order_by(KnowledgeRelation.created_at.desc()).limit(limit).offset(offset)
        total_q = select(func.count()).select_from(q.subquery())
        items = list(self.db.execute(items_q).scalars().all())
        total = int(self.db.execute(total_q).scalar() or 0)
        return items, total

    # -------------------------------------------------------- evidence
    def list_evidence_for_item(self, item_id: str) -> list[EvidenceSpan]:
        self._validate_uuid(item_id)
        q = select(EvidenceSpan).where(EvidenceSpan.knowledge_item_id == item_id)
        return list(self.db.execute(q).scalars().all())

    # -------------------------------------------------------- writes (Phase 3)
    def get_or_create_canonical_entity(
        self,
        *,
        workspace_id: str,
        entity_type: str,
        canonical_name: str,
        aliases: list[str] | None = None,
    ) -> CanonicalEntity:
        normalization_key = self.normalize_entity_name(canonical_name)
        if not normalization_key:
            raise ValueError("canonical_name must contain letters or numbers")
        existing = self.db.execute(
            select(CanonicalEntity).where(
                CanonicalEntity.workspace_id == workspace_id,
                CanonicalEntity.type == entity_type,
                CanonicalEntity.normalization_key == normalization_key,
                CanonicalEntity.is_deleted.is_(False),
            )
        ).scalar_one_or_none()
        if existing:
            merged_aliases = set(existing.aliases or [])
            merged_aliases.update(aliases or [])
            if canonical_name != existing.canonical_name:
                merged_aliases.add(canonical_name)
            existing.aliases = sorted(merged_aliases)
            self.db.flush()
            return existing

        entity = CanonicalEntity(
            id=str(uuid4()),
            workspace_id=workspace_id,
            type=entity_type,
            canonical_name=canonical_name,
            normalization_key=normalization_key,
            aliases=sorted(set(aliases or [])),
            status="extracted_candidate",
            is_deleted=False,
        )
        self.db.add(entity)
        self.db.flush()
        return entity

    def upsert_item(self, payload: KnowledgeItemCreate) -> KnowledgeItem:
        """Create one paper-scoped item, idempotent within an extraction run."""
        if payload.extraction_run_id and payload.item_key:
            existing = self.db.execute(
                select(KnowledgeItem).where(
                    KnowledgeItem.extraction_run_id == payload.extraction_run_id,
                    KnowledgeItem.item_key == payload.item_key,
                    KnowledgeItem.is_deleted.is_(False),
                )
            ).scalar_one_or_none()
            if existing:
                return existing

        item = KnowledgeItem(
            id=str(uuid4()),
            workspace_id=payload.workspace_id,
            paper_id=payload.paper_id,
            canonical_entity_id=payload.canonical_entity_id,
            extraction_run_id=payload.extraction_run_id,
            item_key=payload.item_key,
            type=payload.type,
            canonical_name=payload.canonical_name,
            content=payload.content,
            source_provenance=payload.source_provenance,
            created_by=payload.created_by,
            confidence=payload.confidence,
            status=payload.status,
            version=1,
            is_deleted=False,
        )
        self.db.add(item)
        self.db.flush()
        logger.info("knowledge.created", item_id=item.id, type=item.type)
        return item

    def create_evidence_span(self, payload: EvidenceSpanCreate) -> EvidenceSpan:
        existing = self.db.execute(
            select(EvidenceSpan).where(
                EvidenceSpan.knowledge_item_id == payload.knowledge_item_id,
                EvidenceSpan.artifact_id == payload.artifact_id,
                EvidenceSpan.start_char == payload.start_char,
                EvidenceSpan.end_char == payload.end_char,
                EvidenceSpan.relation == payload.relation,
            )
        ).scalar_one_or_none()
        if existing:
            return existing

        span = EvidenceSpan(
            id=str(uuid4()),
            workspace_id=payload.workspace_id,
            knowledge_item_id=payload.knowledge_item_id,
            paper_id=payload.paper_id,
            artifact_id=payload.artifact_id,
            artifact_kind=payload.artifact_kind,
            artifact_version=payload.artifact_version,
            chunk_index=None,
            start_char=payload.start_char,
            end_char=payload.end_char,
            text=payload.text,
            relation=payload.relation,
            confidence=payload.confidence,
        )
        self.db.add(span)
        self.db.flush()
        return span

    def create_relation(self, payload: KnowledgeRelationCreate) -> KnowledgeRelation:
        existing = self.db.execute(
            select(KnowledgeRelation).where(
                KnowledgeRelation.workspace_id == payload.workspace_id,
                KnowledgeRelation.source_id == payload.source_id,
                KnowledgeRelation.target_id == payload.target_id,
                KnowledgeRelation.relation_type == payload.relation_type,
                KnowledgeRelation.is_deleted.is_(False),
            )
        ).scalar_one_or_none()
        if existing:
            return existing

        rel = KnowledgeRelation(
            id=str(uuid4()),
            workspace_id=payload.workspace_id,
            source_id=payload.source_id,
            target_id=payload.target_id,
            relation_type=payload.relation_type,
            confidence=payload.confidence,
            payload=payload.payload,
            is_deleted=False,
        )
        self.db.add(rel)
        self.db.flush()
        return rel

    def get_run_by_task(self, task_id: str) -> ExtractionRun | None:
        return self.db.execute(
            select(ExtractionRun).where(ExtractionRun.task_id == task_id)
        ).scalar_one_or_none()

    def get_extraction_run(self, run_id: str) -> ExtractionRun:
        try:
            UUID(str(run_id))
        except (ValueError, TypeError) as exc:
            raise ExtractionRunNotFoundError(run_id) from exc
        run = self.db.get(ExtractionRun, run_id)
        if run is None:
            raise ExtractionRunNotFoundError(run_id)
        return run

    def create_rejection(
        self, payload: ExtractionRejectionCreate
    ) -> ExtractionRejection:
        fingerprint_source = {
            "stage": payload.stage,
            "reason_code": payload.reason_code,
            "batch_index": payload.batch_index,
            "raw_payload": payload.raw_payload,
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                fingerprint_source,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        existing = self.db.execute(
            select(ExtractionRejection).where(
                ExtractionRejection.extraction_run_id
                == payload.extraction_run_id,
                ExtractionRejection.fingerprint == fingerprint,
            )
        ).scalar_one_or_none()
        if existing:
            existing.is_deleted = False
            self.db.flush()
            return existing

        rejection = ExtractionRejection(
            id=str(uuid4()),
            workspace_id=payload.workspace_id,
            extraction_run_id=payload.extraction_run_id,
            paper_id=payload.paper_id,
            batch_index=payload.batch_index,
            rejection_kind=payload.rejection_kind,
            stage=payload.stage,
            reason_code=payload.reason_code,
            reason_detail=payload.reason_detail,
            item_type=payload.item_type,
            canonical_name=payload.canonical_name,
            raw_payload=payload.raw_payload,
            evidence_preview=payload.evidence_preview,
            fingerprint=fingerprint,
            is_deleted=False,
        )
        self.db.add(rejection)
        self.db.flush()
        return rejection

    def list_rejections(
        self,
        *,
        workspace_id: str,
        extraction_run_id: str,
        kind_filter: str | None = None,
        stage_filter: str | None = None,
        reason_code_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ExtractionRejection], int]:
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        query = select(ExtractionRejection).where(
            ExtractionRejection.workspace_id == workspace_id,
            ExtractionRejection.extraction_run_id == extraction_run_id,
            ExtractionRejection.is_deleted.is_(False),
        )
        if kind_filter:
            query = query.where(
                ExtractionRejection.rejection_kind == kind_filter
            )
        if stage_filter:
            query = query.where(ExtractionRejection.stage == stage_filter)
        if reason_code_filter:
            query = query.where(
                ExtractionRejection.reason_code == reason_code_filter
            )
        items_query = (
            query.order_by(ExtractionRejection.created_at.asc())
            .limit(limit)
            .offset(offset)
        )
        total_query = select(func.count()).select_from(query.subquery())
        items = list(self.db.execute(items_query).scalars().all())
        total = int(self.db.execute(total_query).scalar() or 0)
        return items, total

    @staticmethod
    def normalize_entity_name(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        return re.sub(r"[\W_]+", "", normalized)

    @staticmethod
    def _validate_uuid(value: str) -> None:
        try:
            UUID(str(value))
        except (ValueError, TypeError) as e:
            raise KnowledgeItemNotFoundError(value) from e
