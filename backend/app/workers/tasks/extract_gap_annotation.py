"""Celery task for fine-tuned Schema 3.0 paper extraction."""

from __future__ import annotations

import hashlib
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.domains.artifact.models import Artifact
from app.domains.artifact.service import ArtifactService
from app.domains.gap.markdown import compact_markdown
from app.domains.gap.models import PaperGapAnnotation
from app.domains.gap.prompt import PROMPT_VERSION
from app.domains.gap.service import GapService
from app.domains.paper.models import Paper
from app.domains.task.models import Task
from app.domains.task.schemas import TaskCreate
from app.domains.task.service import TaskService
from app.gateway.gap_extractor import GapExtractorUnavailableError, OllamaGapExtractor
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="gapmind.extract_gap_annotation", bind=True)
def extract_gap_annotation_task(self, task_id: str) -> dict:
    configure_logging()
    db: Session = SessionLocal()
    try:
        return _run_gap_extraction(db, task_id)
    except Exception as exc:
        db.rollback()
        try:
            task = db.get(Task, task_id)
            if task is not None and task.status == "running":
                TaskService(db).transition(
                    task_id, "failed", progress=1.0, error=str(exc)
                )
        except Exception:
            db.rollback()
        logger.exception("gap_extraction.failed", task_id=task_id, error=str(exc))
        raise
    finally:
        db.close()


def _run_gap_extraction(
    db: Session,
    task_id: str,
    *,
    extractor: OllamaGapExtractor | None = None,
) -> dict:
    tasks = TaskService(db)
    task = tasks.transition(task_id, "running", progress=0.05)
    paper_id = str((task.payload or {}).get("paper_id") or "")
    force = bool((task.payload or {}).get("force"))
    paper = db.get(Paper, paper_id)
    if paper is None or paper.is_deleted or paper.workspace_id != task.workspace_id:
        return _fail(tasks, task_id, f"paper not found in workspace: {paper_id}")
    if not paper.parsed_markdown_artifact_id:
        return _fail(tasks, task_id, "paper has no parsed_markdown_artifact")
    artifact = db.get(Artifact, paper.parsed_markdown_artifact_id)
    if artifact is None or artifact.is_deleted:
        return _fail(tasks, task_id, "parsed markdown artifact not found")
    path = ArtifactService(db).resolve_abs_path(artifact)
    if not path.exists():
        return _fail(tasks, task_id, f"parsed markdown file missing: {path}")
    markdown = compact_markdown(path.read_text(encoding="utf-8"))
    if not markdown:
        return _fail(tasks, task_id, "core markdown is empty")
    input_sha256 = hashlib.sha256(markdown.encode("utf-8")).hexdigest()

    row = db.execute(
        select(PaperGapAnnotation).where(
            PaperGapAnnotation.paper_id == paper.id,
            PaperGapAnnotation.input_sha256 == input_sha256,
            PaperGapAnnotation.model_name == settings.gap_extractor_model,
            PaperGapAnnotation.prompt_version == PROMPT_VERSION,
            PaperGapAnnotation.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if row is not None and row.status == "valid" and not force:
        result = {"annotation_id": row.id, "status": "valid", "idempotent": True}
        tasks.transition(task_id, "succeeded", progress=1.0, result=result)
        return result
    if row is None:
        row = PaperGapAnnotation(
            id=str(uuid4()),
            workspace_id=paper.workspace_id,
            paper_id=paper.id,
            artifact_id=artifact.id,
            task_id=task_id,
            input_sha256=input_sha256,
            schema_version="3.0",
            prompt_version=PROMPT_VERSION,
            model_provider="ollama",
            model_name=settings.gap_extractor_model,
            model_digest=settings.gap_extractor_model_digest or None,
            model_parameters={},
            status="running",
            attempts=0,
            raw_responses=[],
            output=None,
            validation_errors=[],
            is_deleted=False,
        )
        db.add(row)
    else:
        row.task_id = task_id
        row.status = "running"
        row.attempts = 0
        row.raw_responses = []
        row.output = None
        row.validation_errors = []
    db.commit()
    tasks.update_progress(task_id, 0.20)

    model = extractor or OllamaGapExtractor()
    row.model_parameters = model.model_parameters
    try:
        result = model.extract(markdown)
    except GapExtractorUnavailableError as exc:
        message = str(exc)
        row.status = "invalid"
        row.validation_errors = [message]
        row.output = None
        db.commit()
        return _fail(
            tasks,
            task_id,
            message,
            result={
                "annotation_id": row.id,
                "status": "unavailable",
                "retryable": True,
            },
        )
    row.attempts = result.attempts
    row.raw_responses = result.raw_responses
    row.validation_errors = result.validation_errors
    row.output = result.output.model_dump(mode="json") if result.output else None
    row.status = "valid" if result.output else "invalid"
    db.commit()
    if result.output is None:
        failed = {
            "annotation_id": row.id,
            "status": "invalid",
            "attempts": row.attempts,
            "validation_errors": row.validation_errors,
        }
        return _fail(tasks, task_id, "gap annotation failed validation", result=failed)

    GapService(db).assign_annotation(row)
    succeeded = {
        "annotation_id": row.id,
        "status": "valid",
        "attempts": row.attempts,
    }
    tasks.transition(task_id, "succeeded", progress=1.0, result=succeeded)
    return succeeded


def _fail(
    service: TaskService, task_id: str, error: str, *, result: dict | None = None
) -> dict:
    service.transition(task_id, "failed", progress=1.0, error=error, result=result)
    return {"status": "failed", "error": error, **(result or {})}


def _has_valid_annotation(db: Session, paper_id: str) -> bool:
    """True if the paper already has a valid annotation for the CURRENT model
    + prompt version (the demo corpus: papers are parsed once, so a valid
    annotation means re-extraction would just short-circuit idempotently)."""
    row = db.execute(
        select(PaperGapAnnotation.id).where(
            PaperGapAnnotation.paper_id == paper_id,
            PaperGapAnnotation.model_name == settings.gap_extractor_model,
            PaperGapAnnotation.prompt_version == PROMPT_VERSION,
            PaperGapAnnotation.status == "valid",
            PaperGapAnnotation.is_deleted.is_(False),
        ).limit(1)
    ).scalars().first()
    return row is not None


def spawn_gap_extraction(
    db: Session,
    paper_id: str,
    workspace_id: str,
    *,
    force: bool = False,
) -> tuple[str | None, bool]:
    """Create (or reuse) a gap-extraction task for a paper.

    Returns ``(task_id, skipped)``. ``skipped=True`` means the paper already has
    a valid annotation for the current model + prompt and no task was created
    (so "抽取已解析论文" on a large corpus only actually enqueues new papers).
    """
    paper = db.get(Paper, paper_id)
    if paper is None or paper.is_deleted or paper.workspace_id != workspace_id:
        raise ValueError(f"paper not found in workspace: {paper_id}")
    if not paper.parsed_markdown_artifact_id:
        raise ValueError(f"paper has no parsed markdown: {paper_id}")

    if not force and _has_valid_annotation(db, paper_id):
        return None, True

    active = db.execute(
        select(Task).where(
            Task.workspace_id == workspace_id,
            Task.task_type == "extract_gap_annotation",
            Task.status.in_(["queued", "running"]),
            Task.is_deleted.is_(False),
        )
    ).scalars()
    for item in active:
        if (item.payload or {}).get("paper_id") == paper_id:
            return item.id, False

    task = TaskService(db).create(
        TaskCreate(
            workspace_id=workspace_id,
            task_type="extract_gap_annotation",
            payload={"paper_id": paper_id, "force": force},
        )
    )
    async_result = extract_gap_annotation_task.delay(task.id)
    task.celery_task_id = async_result.id
    db.commit()
    return task.id, False

