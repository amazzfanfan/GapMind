"""Celery entry point for a durable Discover Agent run."""

from __future__ import annotations

from app.db.session import SessionLocal
from app.domains.discover.service import DiscoverService
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
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def spawn_discover_task(run_id: str) -> str:
    """Dispatch a run and return the Celery task id."""
    result = run_discover_task.delay(run_id)
    return str(result.id)
