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
from app.domains.gap.validation import classify_failure_kind
from app.domains.paper.models import Paper
from app.domains.task.models import Task
from app.domains.task.schemas import TaskCreate
from app.domains.task.service import TaskService
from app.gateway.gap_extractor import (
    GapExtractor,
    GapExtractorUnavailableError,
    OllamaGapExtractor,
    RemoteGapExtractor,
)
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
    extractor: GapExtractor | None = None,
) -> dict:
    tasks = TaskService(db)
    task = tasks.transition(task_id, "running", progress=0.05)
    paper_id = str((task.payload or {}).get("paper_id") or "")
    force = bool((task.payload or {}).get("force"))
    paper = db.get(Paper, paper_id)
    if paper is None or paper.is_deleted or paper.workspace_id != task.workspace_id:
        return _fail(tasks, task_id, f"paper not found in workspace: {paper_id}")
    if not force:
        existing = _get_valid_annotation(db, paper_id)
        if existing is not None:
            result = {
                "annotation_id": existing.id,
                "status": "valid",
                "provider": existing.model_provider,
                "idempotent": True,
            }
            tasks.transition(task_id, "succeeded", progress=1.0, result=result)
            return result
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
            fallback_reason=None,
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
        row.fallback_reason = None
    db.commit()
    tasks.update_progress(task_id, 0.20)

    model = extractor or OllamaGapExtractor()
    row.model_parameters = model.model_parameters
    try:
        result = model.extract(markdown)
    except GapExtractorUnavailableError as exc:
        message = str(exc)
        _store_failed_annotation(
            row,
            provider="ollama",
            model=settings.gap_extractor_model,
            attempts=0,
            raw_responses=[],
            validation_errors=[message],
            fallback_reason="local_model_unavailable",
            failure_kind="model_unavailable",
        )
        db.commit()
        return _try_remote_fallback(
            db,
            tasks,
            task_id,
            row,
            markdown,
            local_error=message,
            local_status="unavailable",
            local_failure_kind="model_unavailable",
            force=force,
        )
    except RuntimeError:
        message = "本地研究空白模型返回空响应，请检查服务状态后重试。"
        _store_failed_annotation(
            row,
            provider="ollama",
            model=settings.gap_extractor_model,
            attempts=0,
            raw_responses=[],
            validation_errors=[message],
            fallback_reason="local_model_unavailable",
            failure_kind="model_unavailable",
        )
        db.commit()
        return _try_remote_fallback(
            db,
            tasks,
            task_id,
            row,
            markdown,
            local_error=message,
            local_status="unavailable",
            local_failure_kind="model_unavailable",
            force=force,
        )
    row.attempts = result.attempts
    row.raw_responses = result.raw_responses
    row.validation_errors = result.validation_errors
    row.output = result.output.model_dump(mode="json") if result.output else None
    row.model_provider = result.provider
    row.model_name = result.model or settings.gap_extractor_model
    row.model_parameters = {
        **model.model_parameters,
        "validation_error_categories": result.validation_error_categories,
    }
    row.status = "valid" if result.output else "invalid"
    db.commit()
    if result.output is None:
        failure_kind = classify_failure_kind(markdown, result.validation_errors)
        row.fallback_reason = (
            "local_validation_failed"
            if failure_kind == "invalid_output"
            else failure_kind
        )
        db.commit()
        return _try_remote_fallback(
            db,
            tasks,
            task_id,
            row,
            markdown,
            local_error=_failure_message(failure_kind),
            local_status="invalid",
            local_failure_kind=failure_kind,
            force=force,
        )

    GapService(db).assign_annotation(row)
    row.fallback_reason = None
    db.commit()
    succeeded = {
        "annotation_id": row.id,
        "status": "valid",
        "attempts": row.attempts,
        "provider": row.model_provider,
    }
    tasks.transition(task_id, "succeeded", progress=1.0, result=succeeded)
    return succeeded


def _store_failed_annotation(
    row: PaperGapAnnotation,
    *,
    provider: str,
    model: str,
    attempts: int,
    raw_responses: list[str],
    validation_errors: list[str],
    fallback_reason: str,
    failure_kind: str,
) -> None:
    row.model_provider = provider
    row.model_name = model
    row.attempts = attempts
    row.raw_responses = raw_responses
    row.output = None
    row.validation_errors = validation_errors
    row.fallback_reason = fallback_reason
    row.status = "invalid"
    row.model_parameters = {
        **(row.model_parameters or {}),
        "failure_kind": failure_kind,
    }


def _failure_message(failure_kind: str) -> str:
    if failure_kind == "content_insufficient":
        return "论文 Markdown 内容不足，无法可靠生成研究空白标注；请补充解析内容后重试。"
    if failure_kind == "not_applicable":
        return "论文可能不适用于研究空白 Schema（例如综述或教程类），未生成空白标注。"
    return "gap annotation failed validation"


def _remote_is_configured() -> bool:
    return bool(
        settings.gap_extractor_remote_enabled
        and settings.gap_extractor_remote_base_url
        and settings.gap_extractor_remote_api_key
        and settings.gap_extractor_remote_model
    )


def _try_remote_fallback(
    db: Session,
    tasks: TaskService,
    task_id: str,
    local_row: PaperGapAnnotation,
    markdown: str,
    *,
    local_error: str,
    local_status: str,
    local_failure_kind: str,
    force: bool,
) -> dict:
    base_result = {
        "annotation_id": local_row.id,
        "status": local_status,
        "attempts": local_row.attempts,
        "validation_errors": local_row.validation_errors,
        "fallback_reason": local_row.fallback_reason,
        "provider": local_row.model_provider,
    }
    if local_status == "unavailable":
        base_result["retryable"] = True
    if local_failure_kind in {"content_insufficient", "not_applicable"}:
        return _fail(tasks, task_id, local_error, result=base_result)
    if not _remote_is_configured():
        logger.warning(
            "gap_extraction.remote_fallback_skipped",
            task_id=task_id,
            paper_id=local_row.paper_id,
            reason="remote_fallback_not_configured",
        )
        local_row.fallback_reason = "remote_fallback_not_configured"
        db.commit()
        base_result["fallback_reason"] = local_row.fallback_reason
        return _fail(tasks, task_id, local_error, result=base_result)

    remote = RemoteGapExtractor()
    logger.info(
        "gap_extraction.remote_fallback_started",
        task_id=task_id,
        paper_id=local_row.paper_id,
        model=remote.model,
        reason=(
            "local_model_unavailable"
            if local_status == "unavailable"
            else "local_validation_failed"
        ),
    )
    tasks.update_progress(task_id, 0.85)
    remote_row = _get_or_create_remote_row(
        db,
        local_row,
        model=remote.model,
        force=force,
    )
    if remote_row.status == "valid" and not force:
        GapService(db).assign_annotation(remote_row)
        succeeded = {
            "annotation_id": remote_row.id,
            "status": "valid",
            "attempts": remote_row.attempts,
            "provider": remote_row.model_provider,
            "fallback_reason": remote_row.fallback_reason,
            "remote_fallback": True,
        }
        tasks.transition(task_id, "succeeded", progress=1.0, result=succeeded)
        return succeeded

    remote_row.model_parameters = remote.model_parameters
    remote_row.fallback_reason = "local_model_unavailable" if local_status == "unavailable" else "local_validation_failed"
    try:
        # JSON Output only guarantees syntactically valid JSON. The adapter
        # re-runs the same semantic validator and feeds its errors back to
        # the model before the result can become a board annotation.
        remote_result = remote.extract(markdown)
    except GapExtractorUnavailableError as exc:
        message = str(exc)
        _store_failed_annotation(
            remote_row,
            provider=remote.provider,
            model=remote.model,
            attempts=0,
            raw_responses=[],
            validation_errors=[message],
            fallback_reason=remote_row.fallback_reason,
            failure_kind="remote_model_unavailable",
        )
        db.commit()
        return _fail(
            tasks,
            task_id,
            message,
            result={
                "annotation_id": remote_row.id,
                "status": "unavailable",
                "retryable": True,
                "provider": remote_row.model_provider,
                "fallback_reason": remote_row.fallback_reason,
                "local_error": local_error,
                "remote_fallback": True,
            },
        )

    remote_row.model_provider = remote_result.provider
    remote_row.model_name = remote_result.model or remote.model
    remote_row.model_parameters = {
        **remote.model_parameters,
        "validation_error_categories": remote_result.validation_error_categories,
    }
    remote_row.attempts = remote_result.attempts
    remote_row.raw_responses = remote_result.raw_responses
    remote_row.validation_errors = remote_result.validation_errors
    remote_row.output = remote_result.output.model_dump(mode="json") if remote_result.output else None
    remote_row.status = "valid" if remote_result.output else "invalid"
    db.commit()
    if remote_result.output is None:
        failure_kind = classify_failure_kind(markdown, remote_result.validation_errors)
        if failure_kind in {"content_insufficient", "not_applicable"}:
            remote_row.fallback_reason = failure_kind
        db.commit()
        return _fail(
            tasks,
            task_id,
            _failure_message(failure_kind),
            result={
                "annotation_id": remote_row.id,
                "status": "invalid",
                "attempts": remote_row.attempts,
                "validation_errors": remote_row.validation_errors,
                "provider": remote_row.model_provider,
                "fallback_reason": remote_row.fallback_reason,
                "local_error": local_error,
                "remote_fallback": True,
            },
        )

    GapService(db).assign_annotation(remote_row)
    succeeded = {
        "annotation_id": remote_row.id,
        "status": "valid",
        "attempts": remote_row.attempts,
        "provider": remote_row.model_provider,
        "fallback_reason": remote_row.fallback_reason,
        "remote_fallback": True,
    }
    tasks.transition(task_id, "succeeded", progress=1.0, result=succeeded)
    return succeeded


def _get_or_create_remote_row(
    db: Session,
    local_row: PaperGapAnnotation,
    *,
    model: str,
    force: bool,
) -> PaperGapAnnotation:
    row = db.execute(
        select(PaperGapAnnotation).where(
            PaperGapAnnotation.paper_id == local_row.paper_id,
            PaperGapAnnotation.input_sha256 == local_row.input_sha256,
            PaperGapAnnotation.model_name == model,
            PaperGapAnnotation.prompt_version == local_row.prompt_version,
            PaperGapAnnotation.is_deleted.is_(False),
        )
    ).scalar_one_or_none()
    if row is None:
        row = PaperGapAnnotation(
            id=str(uuid4()),
            workspace_id=local_row.workspace_id,
            paper_id=local_row.paper_id,
            artifact_id=local_row.artifact_id,
            task_id=local_row.task_id,
            input_sha256=local_row.input_sha256,
            schema_version=local_row.schema_version,
            prompt_version=local_row.prompt_version,
            model_provider="remote",
            model_name=model,
            model_digest=None,
            model_parameters={},
            status="running",
            attempts=0,
            raw_responses=[],
            output=None,
            validation_errors=[],
            fallback_reason=None,
            is_deleted=False,
        )
        db.add(row)
    elif force or row.status != "valid":
        row.task_id = local_row.task_id
        row.status = "running"
        row.attempts = 0
        row.raw_responses = []
        row.output = None
        row.validation_errors = []
    db.flush()
    return row


def _fail(
    service: TaskService, task_id: str, error: str, *, result: dict | None = None
) -> dict:
    service.transition(task_id, "failed", progress=1.0, error=error, result=result)
    return {"status": "failed", "error": error, **(result or {})}


def _has_valid_annotation(db: Session, paper_id: str) -> bool:
    """True if the paper already has any valid annotation.

    A valid result from the local model or the configured remote fallback is
    already usable by the board. Prompt/model versions are provenance for
    re-extraction and auditing, not a reason for the incremental "extract all
    parsed papers" action to rerun an entire corpus. Explicit ``force=True``
    remains the opt-in path for re-extraction.
    """
    return _get_valid_annotation(db, paper_id) is not None


def _get_valid_annotation(db: Session, paper_id: str) -> PaperGapAnnotation | None:
    return db.execute(
        select(PaperGapAnnotation).where(
            PaperGapAnnotation.paper_id == paper_id,
            PaperGapAnnotation.status == "valid",
            PaperGapAnnotation.is_deleted.is_(False),
        ).limit(1)
    ).scalars().first()


def spawn_gap_extraction(
    db: Session,
    paper_id: str,
    workspace_id: str,
    *,
    force: bool = False,
) -> tuple[str | None, bool]:
    """Create (or reuse) a gap-extraction task for a paper.

    Returns ``(task_id, skipped)``. ``skipped=True`` means the paper already has
    a valid annotation from any provider/version and no task was created (so
    "抽取已解析论文" on a large corpus only actually enqueues new papers).
    Use ``force=True`` when a prompt/model migration intentionally requires a
    re-extraction.
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
            payload={
                "paper_id": paper_id,
                "force": force,
            },
        )
    )
    async_result = extract_gap_annotation_task.delay(task.id)
    task.celery_task_id = async_result.id
    db.commit()
    return task.id, False

