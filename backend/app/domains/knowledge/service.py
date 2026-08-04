"""Knowledge service layer (Phase 3: read + write)."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.knowledge.models import (
    CanonicalEntity,
    EvidenceSpan,
    ExtractionRejection,
    ExtractionRun,
    KnowledgeItem,
    KnowledgeRelation,
    PaperMention,
)
from app.domains.knowledge.schemas import (
    EvidenceSpanCreate,
    ExtractionRejectionCreate,
    KnowledgeItemCreate,
    KnowledgeItemReview,
    KnowledgeRelationCreate,
)
from app.domains.paper.models import Paper

logger = get_logger(__name__)


class KnowledgeItemNotFoundError(Exception):
    def __init__(self, item_id: str) -> None:
        super().__init__(f"Knowledge item not found: {item_id}")
        self.item_id = item_id


class ExtractionRunNotFoundError(Exception):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"Extraction run not found: {run_id}")
        self.run_id = run_id


class KnowledgeItemReviewError(ValueError):
    """Raised when a human review payload is rejected by the service.

    Subclasses ``ValueError`` so existing callers that catch generic value
    errors continue to work, but the new central exception handler maps it
    to a 422 with error code ``invalid_review``.
    """


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
        paper_id: str | None = None,
        query_text: str | None = None,
        min_confidence: float | None = None,
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
        if paper_id:
            q = q.where(KnowledgeItem.paper_id == paper_id)
        if query_text:
            q = q.where(
                KnowledgeItem.canonical_name.ilike(f"%{query_text.strip()}%")
            )
        if min_confidence is not None:
            q = q.where(KnowledgeItem.confidence >= min_confidence)
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

    def graph(
        self,
        *,
        workspace_id: str,
        type_filter: str | None = None,
        paper_id: str | None = None,
        query_text: str | None = None,
        min_confidence: float | None = None,
        relation_type: str | None = None,
        limit: int = 250,
    ) -> tuple[list[KnowledgeItem], list[KnowledgeRelation], int, int]:
        """Return a bounded graph projection for a workspace.

        Relations are restricted to the selected node set so the frontend
        receives a self-contained graph and does not need to join IDs itself.
        """
        limit = max(1, min(limit, 500))
        item_query = select(KnowledgeItem).where(
            KnowledgeItem.workspace_id == workspace_id,
            KnowledgeItem.is_deleted.is_(False),
        )
        if type_filter:
            item_query = item_query.where(KnowledgeItem.type == type_filter)
        if paper_id:
            item_query = item_query.where(KnowledgeItem.paper_id == paper_id)
        if query_text:
            item_query = item_query.where(
                KnowledgeItem.canonical_name.ilike(f"%{query_text.strip()}%")
            )
        if min_confidence is not None:
            item_query = item_query.where(KnowledgeItem.confidence >= min_confidence)

        total_nodes_query = select(func.count()).select_from(item_query.subquery())
        total_nodes = int(self.db.execute(total_nodes_query).scalar() or 0)
        items = list(
            self.db.execute(
                item_query.order_by(KnowledgeItem.confidence.desc(), KnowledgeItem.created_at.desc())
                .limit(limit)
            ).scalars().all()
        )

        node_ids = [item.id for item in items]
        if not node_ids:
            return [], [], total_nodes, 0

        relation_query = select(KnowledgeRelation).where(
            KnowledgeRelation.workspace_id == workspace_id,
            KnowledgeRelation.is_deleted.is_(False),
            KnowledgeRelation.source_id.in_(node_ids),
            KnowledgeRelation.target_id.in_(node_ids),
        )
        if relation_type:
            relation_query = relation_query.where(
                KnowledgeRelation.relation_type == relation_type
            )
        relations = list(
            self.db.execute(
                relation_query.order_by(KnowledgeRelation.confidence.desc())
            ).scalars().all()
        )
        return items, relations, total_nodes, len(relations)

    def graph_projection(
        self,
        *,
        workspace_id: str,
        type_filter: str | None = None,
        paper_id: str | None = None,
        query_text: str | None = None,
        min_confidence: float | None = None,
        relation_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ):
        """Build a paged graph with paper/entity/mention structural nodes."""
        from app.domains.knowledge.schemas import (
            KnowledgeGraphEdgeRead,
            KnowledgeGraphNodeRead,
        )

        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        item_query = self._filtered_item_query(
            workspace_id=workspace_id,
            type_filter=type_filter,
            paper_id=paper_id,
            query_text=query_text,
            min_confidence=min_confidence,
        )
        total_knowledge = int(
            self.db.execute(select(func.count()).select_from(item_query.subquery())).scalar() or 0
        )
        items = list(
            self.db.execute(
                item_query.order_by(
                    KnowledgeItem.confidence.desc(), KnowledgeItem.created_at.desc()
                ).limit(limit).offset(offset)
            ).scalars().all()
        )
        nodes, edges, structural_total, mention_truncated = self._build_projection(
            workspace_id=workspace_id,
            items=items,
            relation_type=relation_type,
            node_limit=limit,
        )
        total_nodes = total_knowledge + structural_total
        total_edges = len(edges)
        truncated = (
            offset + len(items) < total_knowledge
            or offset > 0
            or mention_truncated
        )
        return nodes, edges, total_nodes, total_edges, truncated

    def graph_neighbors(
        self,
        *,
        workspace_id: str,
        node_id: str,
        depth: int = 1,
        limit: int = 100,
        relation_type: str | None = None,
    ):
        """Return a bounded neighborhood for a graph node.

        Node IDs use ``paper:``, ``entity:``, ``mention:`` prefixes for the
        structural layers; knowledge item IDs remain unprefixed for backward
        compatibility with the original graph API.
        """
        from app.domains.knowledge.schemas import (
            KnowledgeGraphEdgeRead,
            KnowledgeGraphNodeRead,
        )

        limit = max(1, min(limit, 200))
        depth = max(1, min(depth, 2))
        kind, raw_id = self._split_graph_node_id(node_id)
        items: list[KnowledgeItem] = []
        extra_paper_ids: set[str] = set()
        extra_entity_ids: set[str] = set()
        if kind == "knowledge":
            seed = self.get_item(raw_id)
            if seed.workspace_id != workspace_id:
                raise KnowledgeItemNotFoundError(raw_id)
            visited = {seed.id}
            frontier = {seed.id}
            for _ in range(depth):
                relation_query = select(KnowledgeRelation).where(
                    KnowledgeRelation.workspace_id == workspace_id,
                    KnowledgeRelation.is_deleted.is_(False),
                    or_(
                        KnowledgeRelation.source_id.in_(frontier),
                        KnowledgeRelation.target_id.in_(frontier),
                    ),
                )
                relation_ids = set()
                for relation in self.db.execute(relation_query).scalars().all():
                    relation_ids.add(relation.source_id)
                    relation_ids.add(relation.target_id)
                frontier = relation_ids - visited
                visited.update(relation_ids)
                if not frontier:
                    break
            items = list(
                self.db.execute(
                    select(KnowledgeItem).where(
                        KnowledgeItem.id.in_(list(visited)),
                        KnowledgeItem.workspace_id == workspace_id,
                        KnowledgeItem.is_deleted.is_(False),
                    )
                ).scalars().all()
            )
        elif kind == "paper":
            extra_paper_ids.add(raw_id)
            items = list(
                self.db.execute(
                    select(KnowledgeItem).where(
                        KnowledgeItem.workspace_id == workspace_id,
                        KnowledgeItem.paper_id == raw_id,
                        KnowledgeItem.is_deleted.is_(False),
                    ).order_by(KnowledgeItem.confidence.desc()).limit(limit)
                ).scalars().all()
            )
        elif kind == "entity":
            extra_entity_ids.add(raw_id)
            items = list(
                self.db.execute(
                    select(KnowledgeItem).where(
                        KnowledgeItem.workspace_id == workspace_id,
                        KnowledgeItem.canonical_entity_id == raw_id,
                        KnowledgeItem.is_deleted.is_(False),
                    ).order_by(KnowledgeItem.confidence.desc()).limit(limit)
                ).scalars().all()
            )
        elif kind == "mention":
            mention = self.db.get(PaperMention, raw_id)
            if mention is None or mention.is_deleted or mention.workspace_id != workspace_id:
                raise KnowledgeItemNotFoundError(raw_id)
            extra_paper_ids.add(mention.paper_id)
            extra_entity_ids.add(mention.canonical_entity_id)
            if mention.knowledge_item_id:
                item = self.db.get(KnowledgeItem, mention.knowledge_item_id)
                if item and not item.is_deleted and item.workspace_id == workspace_id:
                    items = [item]
        else:
            raise KnowledgeItemNotFoundError(node_id)

        nodes, edges, _, _ = self._build_projection(
            workspace_id=workspace_id,
            items=items,
            relation_type=relation_type,
            node_limit=limit,
            extra_paper_ids=extra_paper_ids,
            extra_entity_ids=extra_entity_ids,
            forced_mention_id=raw_id if kind == "mention" else None,
        )
        return nodes, edges

    def _filtered_item_query(
        self,
        *,
        workspace_id: str,
        type_filter: str | None,
        paper_id: str | None,
        query_text: str | None,
        min_confidence: float | None,
    ):
        query = select(KnowledgeItem).where(
            KnowledgeItem.workspace_id == workspace_id,
            KnowledgeItem.is_deleted.is_(False),
        )
        if type_filter:
            query = query.where(KnowledgeItem.type == type_filter)
        if paper_id:
            query = query.where(KnowledgeItem.paper_id == paper_id)
        if query_text:
            query = query.where(KnowledgeItem.canonical_name.ilike(f"%{query_text.strip()}%"))
        if min_confidence is not None:
            query = query.where(KnowledgeItem.confidence >= min_confidence)
        return query

    def _build_projection(
        self,
        *,
        workspace_id: str,
        items: list[KnowledgeItem],
        relation_type: str | None,
        node_limit: int,
        extra_paper_ids: set[str] | None = None,
        extra_entity_ids: set[str] | None = None,
        forced_mention_id: str | None = None,
    ):
        from app.domains.knowledge.schemas import (
            KnowledgeGraphEdgeRead,
            KnowledgeGraphNodeRead,
        )

        paper_ids = {item.paper_id for item in items if item.paper_id}
        paper_ids.update(extra_paper_ids or set())
        entity_ids = {item.canonical_entity_id for item in items if item.canonical_entity_id}
        entity_ids.update(extra_entity_ids or set())
        papers = list(
            self.db.execute(
                select(Paper).where(
                    Paper.id.in_(list(paper_ids)),
                    Paper.workspace_id == workspace_id,
                    Paper.is_deleted.is_(False),
                )
            ).scalars().all()
        ) if paper_ids else []
        entities = list(
            self.db.execute(
                select(CanonicalEntity).where(
                    CanonicalEntity.id.in_(list(entity_ids)),
                    CanonicalEntity.workspace_id == workspace_id,
                    CanonicalEntity.is_deleted.is_(False),
                )
            ).scalars().all()
        ) if entity_ids else []
        mention_query = select(PaperMention).where(
            PaperMention.workspace_id == workspace_id,
            PaperMention.is_deleted.is_(False),
        )
        if paper_ids or entity_ids:
            mention_query = mention_query.where(
                or_(
                    PaperMention.paper_id.in_(list(paper_ids)) if paper_ids else False,
                    PaperMention.canonical_entity_id.in_(list(entity_ids)) if entity_ids else False,
                )
            )
        if forced_mention_id:
            mention_query = mention_query.where(PaperMention.id == forced_mention_id)
        mention_total = int(
            self.db.execute(select(func.count()).select_from(mention_query.subquery())).scalar() or 0
        )
        mentions = list(
            self.db.execute(
                mention_query.order_by(PaperMention.confidence.desc()).limit(max(1, min(node_limit * 2, 500)))
            ).scalars().all()
        ) if paper_ids or entity_ids or forced_mention_id else []

        nodes: list[KnowledgeGraphNodeRead] = []
        for item in items:
            nodes.append(KnowledgeGraphNodeRead(
                id=item.id,
                label=item.canonical_name,
                type=item.type,
                workspace_id=item.workspace_id,
                paper_id=item.paper_id,
                canonical_entity_id=item.canonical_entity_id,
                confidence=item.confidence,
                status=item.status,
                content=item.content,
                node_kind="knowledge",
                knowledge_item_id=item.id,
            ))
        paper_map = {paper.id: paper for paper in papers}
        for paper in papers:
            nodes.append(KnowledgeGraphNodeRead(
                id=f"paper:{paper.id}", label=paper.title, type="paper",
                workspace_id=workspace_id, confidence=1.0, status=paper.parse_status,
                content={"year": paper.year, "source": paper.source},
                node_kind="paper", paper_title=paper.title,
            ))
        for entity in entities:
            nodes.append(KnowledgeGraphNodeRead(
                id=f"entity:{entity.id}", label=entity.canonical_name,
                type="canonical_entity", workspace_id=workspace_id, confidence=1.0,
                status=entity.status, content={"aliases": entity.aliases},
                node_kind="canonical_entity", entity_type=entity.type,
            ))
        for mention in mentions:
            nodes.append(KnowledgeGraphNodeRead(
                id=f"mention:{mention.id}", label=mention.mention_text[:120],
                type="paper_mention", workspace_id=workspace_id, confidence=mention.confidence,
                status=mention.status, content={"start_char": mention.start_char, "end_char": mention.end_char},
                node_kind="paper_mention", mention_text=mention.mention_text,
                paper_id=mention.paper_id, canonical_entity_id=mention.canonical_entity_id,
                knowledge_item_id=mention.knowledge_item_id,
            ))

        edges: list[KnowledgeGraphEdgeRead] = []
        item_ids = [item.id for item in items]
        if item_ids:
            rel_query = select(KnowledgeRelation).where(
                KnowledgeRelation.workspace_id == workspace_id,
                KnowledgeRelation.is_deleted.is_(False),
                KnowledgeRelation.source_id.in_(item_ids),
                KnowledgeRelation.target_id.in_(item_ids),
            )
            if relation_type:
                rel_query = rel_query.where(KnowledgeRelation.relation_type == relation_type)
            for relation in self.db.execute(rel_query).scalars().all():
                edges.append(KnowledgeGraphEdgeRead(
                    id=relation.id, source=relation.source_id, target=relation.target_id,
                    relation_type=relation.relation_type, confidence=relation.confidence,
                    payload=relation.payload,
                ))
        for item in items:
            if item.paper_id and item.paper_id in paper_map:
                edges.append(KnowledgeGraphEdgeRead(
                    id=f"contains:{item.paper_id}:{item.id}", source=f"paper:{item.paper_id}",
                    target=item.id, relation_type="contains", confidence=1.0,
                ))
            if item.canonical_entity_id and any(e.id == item.canonical_entity_id for e in entities):
                edges.append(KnowledgeGraphEdgeRead(
                    id=f"canonicalizes:{item.id}:{item.canonical_entity_id}", source=item.id,
                    target=f"entity:{item.canonical_entity_id}", relation_type="canonicalizes", confidence=1.0,
                ))
        for mention in mentions:
            edges.append(KnowledgeGraphEdgeRead(
                id=f"mentioned_in:{mention.id}:{mention.paper_id}", source=f"mention:{mention.id}",
                target=f"paper:{mention.paper_id}", relation_type="mentioned_in", confidence=mention.confidence,
            ))
            edges.append(KnowledgeGraphEdgeRead(
                id=f"refers_to:{mention.id}:{mention.canonical_entity_id}", source=f"mention:{mention.id}",
                target=f"entity:{mention.canonical_entity_id}", relation_type="refers_to", confidence=mention.confidence,
            ))
            if mention.knowledge_item_id and any(item.id == mention.knowledge_item_id for item in items):
                edges.append(KnowledgeGraphEdgeRead(
                    id=f"evidences:{mention.id}:{mention.knowledge_item_id}", source=f"mention:{mention.id}",
                    target=mention.knowledge_item_id, relation_type="evidences", confidence=mention.confidence,
                ))
        structural_total = len(papers) + len(entities) + mention_total
        return nodes, edges, structural_total, mention_total > len(mentions)

    @staticmethod
    def _split_graph_node_id(node_id: str) -> tuple[str, str]:
        if ":" in node_id:
            kind, raw_id = node_id.split(":", 1)
            return kind, raw_id
        return "knowledge", node_id

    # -------------------------------------------------------- evidence
    def list_evidence_for_item(self, item_id: str) -> list[EvidenceSpan]:
        self._validate_uuid(item_id)
        q = select(EvidenceSpan).where(EvidenceSpan.knowledge_item_id == item_id)
        return list(self.db.execute(q).scalars().all())

    def review_item(
        self, *, workspace_id: str, item_id: str, payload: KnowledgeItemReview
    ) -> KnowledgeItem:
        item = self.get_item(item_id)
        if item.workspace_id != workspace_id:
            raise KnowledgeItemNotFoundError(item_id)
        if payload.action == "edit":
            if payload.canonical_name is None and payload.content is None and payload.confidence is None:
                raise KnowledgeItemReviewError("edit requires canonical_name, content, or confidence")
            if payload.canonical_name is not None:
                item.canonical_name = payload.canonical_name.strip()
            if payload.content is not None:
                item.content = payload.content
            if payload.confidence is not None:
                item.confidence = payload.confidence
            item.status = "human_confirmed"
        elif payload.action == "confirm":
            item.status = "human_confirmed"
        else:
            item.status = "rejected"
        item.reviewed_by = "user"
        item.reviewed_at = datetime.now(timezone.utc)
        item.review_note = payload.note
        item.version += 1
        self.db.commit()
        self.db.refresh(item)
        return item

    def upsert_paper_mention(
        self,
        *,
        workspace_id: str,
        paper_id: str,
        canonical_entity_id: str,
        knowledge_item_id: str | None,
        mention_text: str,
        artifact_id: str | None,
        start_char: int | None,
        end_char: int | None,
        confidence: float,
    ) -> PaperMention:
        query = select(PaperMention).where(
            PaperMention.paper_id == paper_id,
            PaperMention.canonical_entity_id == canonical_entity_id,
            PaperMention.start_char == start_char,
            PaperMention.end_char == end_char,
        )
        existing = self.db.execute(query).scalar_one_or_none()
        if existing:
            return existing
        mention = PaperMention(
            id=str(uuid4()), workspace_id=workspace_id, paper_id=paper_id,
            canonical_entity_id=canonical_entity_id, knowledge_item_id=knowledge_item_id,
            mention_text=mention_text, artifact_id=artifact_id, start_char=start_char,
            end_char=end_char, confidence=confidence, status="extracted_candidate",
            is_deleted=False,
        )
        self.db.add(mention)
        self.db.flush()
        return mention

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
