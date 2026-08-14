"""Re-dispatch celery tasks for a re-queued Task row.

``TaskService.retry`` transitions a failed Task to ``queued`` in the DB, but the
queued row is only actually processed if the corresponding celery task is
enqueued again. This module maps ``task_type`` back to its celery task so retry
can re-dispatch. Imported lazily inside ``TaskService.retry`` to avoid a
task-domain -> workers import cycle.
"""

from __future__ import annotations

from typing import Any


def redispatch_task(task: Any) -> str | None:
    """Enqueue the celery task matching a re-queued ``Task`` row.

    Returns the new celery task id (or ``None`` for task types with no celery
    task — e.g. a legacy row — in which case the row stays ``queued``).
    """
    if task.task_type == "parse_pdf":
        from app.workers.tasks.parse_pdf import parse_pdf_task

        return str(parse_pdf_task.delay(task.id).id)
    if task.task_type == "extract_knowledge":
        from app.workers.tasks.extract_knowledge import extract_knowledge_task

        return str(extract_knowledge_task.delay(task.id).id)
    if task.task_type == "embed_chunks":
        from app.workers.tasks.embed_chunks import embed_chunks_task

        return str(embed_chunks_task.delay(task.id).id)
    if task.task_type == "extract_gap_annotation":
        from app.workers.tasks.extract_gap_annotation import extract_gap_annotation_task

        return str(extract_gap_annotation_task.delay(task.id).id)
    if task.task_type == "discover_agent":
        # The Discover agent task takes the run id, not the task id.
        run_id = (task.payload or {}).get("run_id")
        if run_id:
            from app.workers.tasks.run_agent import run_agent_task

            return str(run_agent_task.delay(run_id).id)
    return None
