"""extract_knowledge Celery task (Phase 3).

Reads a paper's parsed_markdown artifact, sends it to Deepseek with a
structured extraction prompt, validates the JSON output, and writes
knowledge_items / knowledge_relations / evidence_spans.

State flow:
    Task row:     queued -> running -> succeeded / failed
    Paper row:    extract_status: pending -> extracting -> extracted / failed
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.domains.artifact.models import Artifact
from app.domains.artifact.service import ArtifactService
from app.domains.knowledge.models import (
    EvidenceSpan,
    ExtractionRejection,
    ExtractionRun,
    KnowledgeItem,
    KnowledgeRelation,
)
from app.domains.knowledge.schemas import (
    EvidenceSpanCreate,
    ExtractionItem,
    ExtractionRejectionCreate,
    ExtractionRelation,
    KnowledgeItemCreate,
    KnowledgeRelationCreate,
)
from app.domains.knowledge.service import KnowledgeService
from app.domains.paper.models import Paper
from app.domains.task.models import Task
from app.domains.task.schemas import TaskCreate
from app.domains.task.service import TaskService
from app.domains.timeline.service import TimelineService
from app.gateway.llm import LLMGateway
from app.gateway.prompts.extract_v1 import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.workers.celery_app import celery_app

logger = get_logger(__name__)

MAX_RETRIES = 2
EXTRACTION_ITEM_ADAPTER = TypeAdapter(ExtractionItem)


@celery_app.task(name="gapmind.extract_knowledge", bind=True)
def extract_knowledge_task(self, task_id: str) -> dict:
    """Extract structured knowledge from a parsed paper.

    Args:
        task_id: The Task row ID. Payload must contain {"paper_id": "..."}.
    """
    configure_logging()
    db: Session = SessionLocal()
    try:
        result = _run_extract(db, task_id)
        if result.get("status") == "failed":
            raise RuntimeError(result.get("error") or "knowledge extraction failed")
        return result
    finally:
        db.close()


def _run_extract(db: Session, task_id: str) -> dict:
    task_service = TaskService(db)

    try:
        task = task_service.transition(task_id, "running", progress=0.05)
    except Exception as e:
        logger.error("extract_knowledge.transition_failed", task_id=task_id, error=str(e))
        raise

    paper_id = task.payload.get("paper_id")
    if not paper_id:
        return _fail(task_service, task_id, "task payload missing 'paper_id'")

    paper = db.get(Paper, paper_id)
    if paper is None or paper.is_deleted:
        return _fail(task_service, task_id, f"paper not found: {paper_id}")

    if not paper.parsed_markdown_artifact_id:
        return _fail(task_service, task_id, "paper has no parsed_markdown_artifact")

    md_artifact = db.get(Artifact, paper.parsed_markdown_artifact_id)
    if md_artifact is None or md_artifact.is_deleted:
        return _fail(task_service, task_id, "markdown artifact not found")

    artifact_service = ArtifactService(db)
    md_path = artifact_service.resolve_abs_path(md_artifact)
    if not md_path.exists():
        return _fail(task_service, task_id, f"markdown file missing: {md_path}")

    paper_text = md_path.read_text(encoding="utf-8")
    if not paper_text.strip():
        return _fail(task_service, task_id, "parsed markdown is empty")

    run = _ensure_extraction_run(
        db=db,
        task_id=task_id,
        paper=paper,
        artifact_id=md_artifact.id,
    )
    if run.status == "succeeded":
        result = _run_counts(db, run.id)
        task_service.transition(
            task_id, "succeeded", progress=1.0, result=result
        )
        return {"status": "succeeded", **result, "idempotent": True}

    paper.extract_status = "extracting"
    run.status = "running"
    run.error = None
    run.finished_at = None
    db.commit()
    task_service.update_progress(task_id, 0.15)

    try:
        validated_items: list[dict] = []
        validated_relations: list[dict] = []
        output_item_count = 0
        batches = _split_extraction_batches(paper_text)

        for batch_index, (batch_start, batch_text) in enumerate(batches):
            user_prompt = build_user_prompt(
                title=paper.title,
                authors=paper.authors,
                year=paper.year,
                paper_text=batch_text,
            )
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
            raw_response, parsed = _call_llm_with_retry(
                messages, max_retries=MAX_RETRIES
            )
            if parsed is None:
                _persist_rejections(
                    db,
                    [
                        _make_rejection(
                            run=run,
                            paper=paper,
                            batch_index=batch_index,
                            rejection_kind="output",
                            stage="schema_validation",
                            reason_code="invalid_json_output",
                            reason_detail="LLM output was not valid JSON.",
                            raw_payload={"raw_preview": raw_response[:2000]},
                        )
                    ],
                )
                raise RuntimeError(
                    "LLM output invalid after retries: " + raw_response[:500]
                )

            (
                batch_output_items,
                batch_relations,
                schema_rejections,
                batch_raw_item_count,
            ) = _validate_output_records(
                parsed=parsed,
                run=run,
                paper=paper,
                batch_index=batch_index,
            )
            output_item_count += batch_raw_item_count
            _persist_rejections(db, schema_rejections)

            batch_items, evidence_rejections = _validate_and_rebase_evidence(
                items=batch_output_items,
                paper_text=paper_text,
                batch_text=batch_text,
                batch_start=batch_start,
                batch_index=batch_index,
                run=run,
                paper=paper,
            )
            _persist_rejections(db, evidence_rejections)
            validated_items.extend(batch_items)
            for relation in batch_relations:
                relation_data = relation.model_dump(mode="json")
                relation_data["_batch_index"] = batch_index
                validated_relations.append(relation_data)
            progress = 0.25 + (0.45 * (batch_index + 1) / len(batches))
            task_service.update_progress(task_id, progress)

        if output_item_count > 0 and not validated_items:
            raise RuntimeError(
                "all extracted items were rejected by evidence validation"
            )

        (
            items_count,
            relations_count,
            spans_count,
            _rejected_relation_count,
        ) = _write_extraction(
            db,
            paper,
            run,
            validated_items,
            validated_relations,
        )
        run.status = "succeeded"
        run.finished_at = datetime.now(timezone.utc)
        paper.extract_status = "extracted"
        paper.extracted_at = run.finished_at
        db.commit()
    except Exception as exc:
        db.rollback()
        _mark_extraction_failed(db, task_id, paper_id, str(exc))
        failure_result = {
            "extraction_run_id": run.id,
            **_rejection_counts(db, run.id),
        }
        return _fail(
            task_service,
            task_id,
            str(exc),
            result=failure_result,
        )

    result = {
        "knowledge_items": items_count,
        "knowledge_relations": relations_count,
        "evidence_spans": spans_count,
        "extraction_run_id": run.id,
    }
    result.update(_rejection_counts(db, run.id))
    task_service.transition(task_id, "succeeded", progress=1.0, result=result)

    TimelineService(db).record(
        workspace_id=paper.workspace_id,
        event_type="knowledge.extracted",
        subject_type="paper",
        subject_id=paper.id,
        payload={
            "items": items_count,
            "relations": relations_count,
            "spans": spans_count,
            "rejected_evidence": result["rejected_evidence"],
            "rejected_relations": result["rejected_relations"],
            "rejected_schema": result["rejected_schema"],
        },
    )

    logger.info(
        "extract_knowledge.succeeded",
        paper_id=paper.id,
        task_id=task_id,
        items=items_count,
        relations=relations_count,
    )
    return {"status": "succeeded", **result}


def _ensure_extraction_run(
    *,
    db: Session,
    task_id: str,
    paper: Paper,
    artifact_id: str,
) -> ExtractionRun:
    existing = db.execute(
        select(ExtractionRun).where(ExtractionRun.task_id == task_id)
    ).scalar_one_or_none()
    if existing:
        _attach_run_to_task(db, task_id, existing.id)
        return existing

    run = ExtractionRun(
        id=str(uuid4()),
        workspace_id=paper.workspace_id,
        paper_id=paper.id,
        artifact_id=artifact_id,
        task_id=task_id,
        schema_version="1.0.0",
        prompt_version=PROMPT_VERSION,
        model_provider="deepseek",
        model_name=settings.deepseek_model,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    _attach_run_to_task(db, task_id, run.id)
    return run


def _attach_run_to_task(db: Session, task_id: str, run_id: str) -> None:
    task = db.get(Task, task_id)
    if task is None:
        return
    payload = dict(task.payload or {})
    if payload.get("extraction_run_id") == run_id:
        return
    payload["extraction_run_id"] = run_id
    task.payload = payload
    db.commit()


def _split_extraction_batches(
    text: str,
    *,
    max_chars: int = 40000,
    overlap_chars: int = 1000,
) -> list[tuple[int, str]]:
    """Split a document without silently dropping its tail."""
    if len(text) <= max_chars:
        return [(0, text)]

    batches: list[tuple[int, str]] = []
    start = 0
    while start < len(text):
        hard_end = min(start + max_chars, len(text))
        end = hard_end
        if hard_end < len(text):
            min_split = start + max_chars // 2
            heading = text.rfind("\n## ", min_split, hard_end)
            paragraph = text.rfind("\n\n", min_split, hard_end)
            split_at = heading if heading >= min_split else paragraph
            if split_at >= min_split:
                end = split_at
        if end <= start:
            end = hard_end
        batches.append((start, text[start:end]))
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return batches


def _validate_output_records(
    *,
    parsed: dict,
    run: ExtractionRun,
    paper: Paper,
    batch_index: int,
) -> tuple[
    list[ExtractionItem],
    list[ExtractionRelation],
    list[ExtractionRejectionCreate],
    int,
]:
    """Validate items and relations independently so one bad record is isolated."""
    valid_items: list[ExtractionItem] = []
    valid_relations: list[ExtractionRelation] = []
    rejections: list[ExtractionRejectionCreate] = []

    raw_items = parsed.get("items")
    raw_item_count = len(raw_items) if isinstance(raw_items, list) else 1
    if not isinstance(raw_items, list):
        rejections.append(
            _make_rejection(
                run=run,
                paper=paper,
                batch_index=batch_index,
                rejection_kind="output",
                stage="schema_validation",
                reason_code="items_not_array",
                reason_detail="Top-level items must be an array.",
                raw_payload=_as_payload(raw_items),
            )
        )
        raw_items = []

    for raw_item in raw_items:
        try:
            valid_items.append(
                EXTRACTION_ITEM_ADAPTER.validate_python(raw_item)
            )
        except ValidationError as exc:
            payload = _as_payload(raw_item)
            rejections.append(
                _make_rejection(
                    run=run,
                    paper=paper,
                    batch_index=batch_index,
                    rejection_kind="item",
                    stage="schema_validation",
                    reason_code="invalid_item_schema",
                    reason_detail=_validation_detail(exc),
                    raw_payload=payload,
                    item_type=_string_or_none(payload.get("type")),
                    canonical_name=_string_or_none(
                        payload.get("canonical_name")
                    ),
                    evidence_preview=_string_or_none(
                        payload.get("evidence_text")
                    ),
                )
            )

    raw_relations = parsed.get("relations", [])
    if not isinstance(raw_relations, list):
        rejections.append(
            _make_rejection(
                run=run,
                paper=paper,
                batch_index=batch_index,
                rejection_kind="output",
                stage="schema_validation",
                reason_code="relations_not_array",
                reason_detail="Top-level relations must be an array.",
                raw_payload=_as_payload(raw_relations),
            )
        )
        raw_relations = []

    for raw_relation in raw_relations:
        try:
            valid_relations.append(
                ExtractionRelation.model_validate(raw_relation)
            )
        except ValidationError as exc:
            rejections.append(
                _make_rejection(
                    run=run,
                    paper=paper,
                    batch_index=batch_index,
                    rejection_kind="relation",
                    stage="schema_validation",
                    reason_code="invalid_relation_schema",
                    reason_detail=_validation_detail(exc),
                    raw_payload=_as_payload(raw_relation),
                )
            )

    return valid_items, valid_relations, rejections, raw_item_count


def _make_rejection(
    *,
    run: ExtractionRun,
    paper: Paper,
    batch_index: int | None,
    rejection_kind: str,
    stage: str,
    reason_code: str,
    reason_detail: str,
    raw_payload: dict,
    item_type: str | None = None,
    canonical_name: str | None = None,
    evidence_preview: str | None = None,
) -> ExtractionRejectionCreate:
    return ExtractionRejectionCreate(
        workspace_id=paper.workspace_id,
        extraction_run_id=run.id,
        paper_id=paper.id,
        batch_index=batch_index,
        rejection_kind=rejection_kind,
        stage=stage,
        reason_code=reason_code,
        reason_detail=reason_detail,
        item_type=item_type,
        canonical_name=canonical_name,
        raw_payload=raw_payload,
        evidence_preview=(
            evidence_preview[:500] if evidence_preview else None
        ),
    )


def _as_payload(value: object) -> dict:
    return value if isinstance(value, dict) else {"value": value}


def _validation_detail(exc: ValidationError) -> str:
    return json.dumps(
        exc.errors(include_input=False, include_url=False),
        ensure_ascii=False,
        default=str,
    )[:4000]


def _string_or_none(value: object) -> str | None:
    return str(value) if value is not None else None


def _persist_rejections(
    db: Session, rejections: list[ExtractionRejectionCreate]
) -> None:
    if not rejections:
        return
    service = KnowledgeService(db)
    for rejection in rejections:
        service.create_rejection(rejection)
    db.commit()


def _validate_and_rebase_evidence(
    *,
    items: list[ExtractionItem],
    paper_text: str,
    batch_text: str,
    batch_start: int,
    batch_index: int,
    run: ExtractionRun | None = None,
    paper: Paper | None = None,
) -> tuple[list[dict], list[ExtractionRejectionCreate]]:
    validated: list[dict] = []
    rejections: list[ExtractionRejectionCreate] = []
    seen: set[tuple[str, str, int, int]] = set()

    for item in items:
        evidence_text = item.evidence_text
        try:
            start, end, resolved_text = _resolve_evidence_span(
                paper_text=paper_text,
                batch_text=batch_text,
                batch_start=batch_start,
                reported_start=item.source_provenance.start_char,
                reported_end=item.source_provenance.end_char,
                evidence_text=evidence_text,
            )
        except ValueError as exc:
            logger.warning(
                "extract_knowledge.evidence_rejected",
                batch_index=batch_index,
                item_type=item.type,
                canonical_name=item.canonical_name,
                evidence_preview=evidence_text[:160],
                error=str(exc),
            )
            if run is not None and paper is not None:
                rejections.append(
                    _make_rejection(
                        run=run,
                        paper=paper,
                        batch_index=batch_index,
                        rejection_kind="item",
                        stage="evidence_resolution",
                        reason_code="evidence_not_found",
                        reason_detail=str(exc),
                        raw_payload=item.model_dump(mode="json"),
                        item_type=item.type,
                        canonical_name=item.canonical_name,
                        evidence_preview=evidence_text,
                    )
                )
            continue
        dedupe_key = (
            item.type,
            KnowledgeService.normalize_entity_name(item.canonical_name),
            start,
            end,
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        data = item.model_dump(mode="json")
        data["source_provenance"] = {
            "start_char": start,
            "end_char": end,
            "batch_index": batch_index,
        }
        # Persist the exact artifact slice, not the LLM's whitespace-normalized
        # rendering of it.
        data["evidence_text"] = resolved_text
        validated.append(data)
    return validated, rejections


def _resolve_evidence_span(
    *,
    paper_text: str,
    batch_text: str,
    batch_start: int,
    reported_start: int,
    reported_end: int,
    evidence_text: str,
) -> tuple[int, int, str]:
    """Resolve an exact source span, tolerating only whitespace differences."""
    relative_end = reported_start + len(evidence_text)
    if reported_start >= 0 and batch_text[reported_start:relative_end] == evidence_text:
        start = batch_start + reported_start
        return start, start + len(evidence_text), evidence_text

    if (
        reported_start >= 0
        and paper_text[reported_start : reported_start + len(evidence_text)]
        == evidence_text
    ):
        return reported_start, reported_start + len(evidence_text), evidence_text

    batch_matches = _all_occurrences(batch_text, evidence_text)
    if batch_matches:
        relative_start = _nearest_match(batch_matches, reported_start)
        start = batch_start + relative_start
        return start, start + len(evidence_text), evidence_text

    document_matches = _all_occurrences(paper_text, evidence_text)
    if document_matches:
        expected_positions = [batch_start + reported_start, reported_start]
        start = min(
            document_matches,
            key=lambda match: min(
                abs(match - expected) for expected in expected_positions
            ),
        )
        return start, start + len(evidence_text), evidence_text

    batch_whitespace_matches = _whitespace_equivalent_matches(
        batch_text, evidence_text
    )
    if batch_whitespace_matches:
        relative_start, relative_end = min(
            batch_whitespace_matches,
            key=lambda match: abs(match[0] - reported_start),
        )
        start = batch_start + relative_start
        end = batch_start + relative_end
        return start, end, paper_text[start:end]

    document_whitespace_matches = _whitespace_equivalent_matches(
        paper_text, evidence_text
    )
    if document_whitespace_matches:
        expected_positions = [batch_start + reported_start, reported_start]
        start, end = min(
            document_whitespace_matches,
            key=lambda match: min(
                abs(match[0] - expected) for expected in expected_positions
            ),
        )
        return start, end, paper_text[start:end]

    raise ValueError(
        "evidence_text has no exact or whitespace-equivalent parsed_markdown span"
    )


def _all_occurrences(text: str, needle: str) -> list[int]:
    matches: list[int] = []
    cursor = 0
    while True:
        index = text.find(needle, cursor)
        if index < 0:
            return matches
        matches.append(index)
        cursor = index + 1


def _nearest_match(matches: list[int], expected: int) -> int:
    return min(matches, key=lambda match: abs(match - expected))


def _whitespace_equivalent_matches(
    text: str, evidence_text: str
) -> list[tuple[int, int]]:
    tokens = re.split(r"\s+", evidence_text.strip())
    if not tokens or any(not token for token in tokens):
        return []
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    return [(match.start(), match.end()) for match in re.finditer(pattern, text)]


def _run_counts(db: Session, run_id: str) -> dict:
    item_ids = list(
        db.execute(
            select(KnowledgeItem.id).where(
                KnowledgeItem.extraction_run_id == run_id,
                KnowledgeItem.is_deleted.is_(False),
            )
        ).scalars()
    )
    if not item_ids:
        result = {
            "knowledge_items": 0,
            "knowledge_relations": 0,
            "evidence_spans": 0,
            "extraction_run_id": run_id,
        }
        result.update(_rejection_counts(db, run_id))
        return result
    relation_count = int(
        db.execute(
            select(func.count())
            .select_from(KnowledgeRelation)
            .where(KnowledgeRelation.source_id.in_(item_ids))
        ).scalar()
        or 0
    )
    span_count = int(
        db.execute(
            select(func.count())
            .select_from(EvidenceSpan)
            .where(EvidenceSpan.knowledge_item_id.in_(item_ids))
        ).scalar()
        or 0
    )
    result = {
        "knowledge_items": len(item_ids),
        "knowledge_relations": relation_count,
        "evidence_spans": span_count,
        "extraction_run_id": run_id,
    }
    result.update(_rejection_counts(db, run_id))
    return result


def _rejection_counts(db: Session, run_id: str) -> dict[str, int]:
    base = [
        ExtractionRejection.extraction_run_id == run_id,
        ExtractionRejection.is_deleted.is_(False),
    ]

    def count_where(*conditions: object) -> int:
        return int(
            db.execute(
                select(func.count())
                .select_from(ExtractionRejection)
                .where(*base, *conditions)
            ).scalar()
            or 0
        )

    return {
        "rejected_evidence": count_where(
            ExtractionRejection.stage == "evidence_resolution"
        ),
        "rejected_relations": count_where(
            ExtractionRejection.rejection_kind == "relation"
        ),
        "rejected_schema": count_where(
            ExtractionRejection.stage == "schema_validation"
        ),
        "rejected_total": count_where(),
    }


def _mark_extraction_failed(
    db: Session, task_id: str, paper_id: str, error: str
) -> None:
    run = db.execute(
        select(ExtractionRun).where(ExtractionRun.task_id == task_id)
    ).scalar_one_or_none()
    if run:
        run.status = "failed"
        run.error = error[:4000]
        run.finished_at = datetime.now(timezone.utc)
    paper = db.get(Paper, paper_id)
    if paper:
        paper.extract_status = "failed"
    db.commit()


# ----------------------------------------------------------------- LLM call
def _call_llm_with_retry(
    messages: list[dict], max_retries: int = 2
) -> tuple[str, dict | None]:
    """Call the LLM and parse JSON. Retry on parse failure.

    Uses max_tokens=16384 because a full paper's extraction (methods, tasks,
    datasets, claims, limitations + relations) easily exceeds the default 4096.
    """
    gateway = LLMGateway()
    last_raw = ""
    for attempt in range(max_retries + 1):
        try:
            resp = gateway.chat_completion(messages, temperature=0.1, max_tokens=16384)
            raw = resp.content
            last_raw = raw
            parsed = _parse_llm_json(raw)
            if parsed is not None and "items" in parsed:
                return raw, parsed
            logger.warning(
                "extract_knowledge.parse_retry",
                attempt=attempt,
                raw_preview=raw[:200],
            )
        except Exception as e:
            logger.warning(
                "extract_knowledge.llm_error",
                attempt=attempt,
                error=str(e),
            )
        if attempt < max_retries:
            time.sleep(2)
    return last_raw, None


def _parse_llm_json(raw: str) -> dict | None:
    """Extract JSON from LLM response. Handles ```json fences and trailing commas."""
    # Try extracting from ```json ... ``` block
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
    if m:
        raw = m.group(1).strip()
    # Try to find first { and last }
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    # Remove trailing commas before ] or }
    raw = re.sub(r",\s*([}\]])", r"\1", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# ----------------------------------------------------------------- DB write
def _write_extraction(
    db: Session,
    paper: Paper,
    run: ExtractionRun,
    items: list[dict],
    relations: list[dict],
) -> tuple[int, int, int, int]:
    """Stage an extraction atomically. The caller owns commit/rollback."""
    ks = KnowledgeService(db)

    # Map canonical_name -> knowledge_item_id for relation resolution
    entity_map: dict[tuple[str, str], str] = {}  # (type, canonical_name) -> id

    item_ids: set[str] = set()
    span_ids: set[str] = set()

    for item in items:
        item_type = item["type"]
        canonical_name = item["canonical_name"].strip()
        content = item["content"]
        sp = item["source_provenance"]
        evidence_text = item["evidence_text"]
        normalized_name = ks.normalize_entity_name(canonical_name)
        item_key = hashlib.sha256(
            (
                f"{item_type}|{normalized_name}|"
                f"{sp['start_char']}|{sp['end_char']}"
            ).encode("utf-8")
        ).hexdigest()[:32]

        canonical_entity_id = None
        if item_type in {"method", "task", "dataset"}:
            entity = ks.get_or_create_canonical_entity(
                workspace_id=paper.workspace_id,
                entity_type=item_type,
                canonical_name=canonical_name,
            )
            canonical_entity_id = entity.id

        ki = ks.upsert_item(
            KnowledgeItemCreate(
                workspace_id=paper.workspace_id,
                paper_id=paper.id,
                canonical_entity_id=canonical_entity_id,
                extraction_run_id=run.id,
                item_key=item_key,
                type=item_type,
                canonical_name=canonical_name,
                content=content,
                source_provenance={
                    "paper_id": paper.id,
                    "artifact_id": paper.parsed_markdown_artifact_id,
                    "artifact_kind": "parsed_markdown",
                    "artifact_version": "v1",
                    "start_char": sp["start_char"],
                    "end_char": sp["end_char"],
                    "batch_index": sp["batch_index"],
                    "extracted_by": run.model_name,
                    "extraction_run_id": run.id,
                },
                created_by="agent",
                confidence=item["confidence"],
                status="extracted_candidate",
            )
        )
        entity_map.setdefault((item_type, normalized_name), ki.id)
        item_ids.add(ki.id)

        span = ks.create_evidence_span(
            EvidenceSpanCreate(
                workspace_id=paper.workspace_id,
                knowledge_item_id=ki.id,
                paper_id=paper.id,
                artifact_id=paper.parsed_markdown_artifact_id,
                artifact_kind="parsed_markdown",
                artifact_version="v1",
                start_char=sp["start_char"],
                end_char=sp["end_char"],
                text=evidence_text,
                relation="supports",
                confidence=item["confidence"],
            )
        )
        span_ids.add(span.id)
        if canonical_entity_id:
            ks.upsert_paper_mention(
                workspace_id=paper.workspace_id,
                paper_id=paper.id,
                canonical_entity_id=canonical_entity_id,
                knowledge_item_id=ki.id,
                mention_text=evidence_text,
                artifact_id=paper.parsed_markdown_artifact_id,
                start_char=sp["start_char"],
                end_char=sp["end_char"],
                confidence=item["confidence"],
            )

    # Create relations
    relation_ids: set[str] = set()
    rejected_relations = 0
    for rel in relations:
        source_key = (
            rel["source_type"],
            ks.normalize_entity_name(rel["source_name"]),
        )
        target_key = (
            rel["target_type"],
            ks.normalize_entity_name(rel["target_name"]),
        )
        source_id = entity_map.get(source_key)
        target_id = entity_map.get(target_key)
        relation_type = _normalize_relation_type(rel)

        if source_id and target_id and relation_type:
            relation = ks.create_relation(
                KnowledgeRelationCreate(
                    workspace_id=paper.workspace_id,
                    source_id=source_id,
                    target_id=target_id,
                    relation_type=relation_type,
                    confidence=rel["confidence"],
                    payload={"extraction_run_id": run.id},
                )
            )
            relation_ids.add(relation.id)
        else:
            rejected_relations += 1
            reason_code = (
                "unsupported_relation"
                if relation_type is None
                else "unresolved_endpoint"
            )
            ks.create_rejection(
                _make_rejection(
                    run=run,
                    paper=paper,
                    batch_index=rel.get("_batch_index"),
                    rejection_kind="relation",
                    stage="relation_resolution",
                    reason_code=reason_code,
                    reason_detail=(
                        "Relation type is not supported."
                        if relation_type is None
                        else "Source or target item was not accepted."
                    ),
                    raw_payload={
                        key: value
                        for key, value in rel.items()
                        if key != "_batch_index"
                    },
                )
            )
            logger.warning(
                "extract_knowledge.relation_rejected",
                source_type=rel["source_type"],
                source_name=rel["source_name"],
                relation=rel["relation"],
                target_type=rel["target_type"],
                target_name=rel["target_name"],
                reason=reason_code,
            )

    db.flush()
    return (
        len(item_ids),
        len(relation_ids),
        len(span_ids),
        rejected_relations,
    )


def _normalize_relation_type(relation: dict) -> str | None:
    value = str(relation.get("relation", "")).strip().lower()
    allowed = {
        "extends",
        "compares_with",
        "evaluates_on",
        "supports",
        "qualifies",
        "contradicts",
        "related_to",
    }
    if value in allowed:
        return value
    if value == "uses":
        if relation.get("target_type") == "dataset":
            return "evaluates_on"
        return "related_to"
    return None


def _fail(
    task_service: TaskService,
    task_id: str,
    error: str,
    *,
    result: dict | None = None,
) -> dict:
    task_service.transition(
        task_id,
        "failed",
        error=error,
        progress=1.0,
        result=result,
    )
    response = {"status": "failed", "error": error}
    if result:
        response.update(result)
    return response


def spawn_extract_knowledge(db: Session, paper_id: str, workspace_id: str) -> str:
    """Create a Task row and dispatch extract_knowledge."""
    import app.workers.tasks.extract_knowledge  # noqa: F401

    paper = db.get(Paper, paper_id)
    if paper is None or paper.is_deleted or paper.workspace_id != workspace_id:
        raise ValueError(f"paper not found in workspace: {paper_id}")
    if not paper.parsed_markdown_artifact_id:
        raise ValueError(f"paper has no parsed markdown: {paper_id}")

    active_tasks = db.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.task_type == "extract_knowledge",
            Task.status.in_(["queued", "running"]),
            Task.is_deleted.is_(False),
        )
    ).scalars()
    for active_task in active_tasks:
        if (active_task.payload or {}).get("paper_id") == paper_id:
            return active_task.id

    paper.extract_status = "pending"
    db.commit()

    task_service = TaskService(db)
    task = task_service.create(
        TaskCreate(
            workspace_id=workspace_id,
            task_type="extract_knowledge",
            payload={"paper_id": paper_id},
        )
    )
    async_result = extract_knowledge_task.delay(task.id)
    task.celery_task_id = async_result.id
    db.commit()
    logger.info(
        "extract_knowledge.spawned",
        paper_id=paper_id,
        task_id=task.id,
        celery_task_id=async_result.id,
    )
    return task.id
