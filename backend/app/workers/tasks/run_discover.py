"""Celery entry point for a durable Discover Agent run."""

from __future__ import annotations

from app.db.session import SessionLocal
from app.domains.discover.models import DiscoverRun
from app.domains.discover.service import DiscoverRunCancelled, DiscoverService
from app.domains.task.service import TaskService
from app.workers.celery_app import celery_app


@celery_app.task(
    bind=True,
    name="gapmind.run_discover",
    autoretry_for=(TimeoutError,),
    retry_backoff=True,
    max_retries=2,
)
def run_discover_task(self, run_id: str) -> dict:
    del self
    db = SessionLocal()
    try:
        return DiscoverService(db).execute_run(run_id)
    except DiscoverRunCancelled:
        db.rollback()
        run = db.get(DiscoverRun, run_id)
        if run is not None:
            run.status = "cancelled"
            run.stage = "cancelled"
            db.commit()
            if run.task_id:
                try:
                    TaskService(db).transition(run.task_id, "cancelled", progress=run.progress)
                except Exception:
                    pass
        return {"run_id": run_id, "status": "cancelled"}
    except Exception as exc:
        db.rollback()
        # Do not leave a durable run in `running` when a worker exception is
        # not one of the explicitly handled, degraded pipeline outcomes.
        # The run remains retryable through its existing user-facing retry
        # path, while the original exception is still re-raised for Celery.
        run = db.get(DiscoverRun, run_id)
        if run is not None and run.status not in {"succeeded", "cancelled", "failed"}:
            try:
                DiscoverService(db)._fail_run(
                    run,
                    "discover_worker_failed",
                    str(exc)[:4000],
                )
            except Exception:
                db.rollback()
        raise
    finally:
        db.close()


def spawn_discover_task(run_id: str) -> str:
    """Dispatch a run and return the Celery task id."""
    result = run_discover_task.delay(run_id)
    return str(result.id)
