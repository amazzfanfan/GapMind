"""Celery entry points for durable workspace agents and sandbox validation."""

from __future__ import annotations

from sqlalchemy import select

from app.db.session import SessionLocal
from app.domains.agent.models import AgentArtifact, AgentRun
from app.domains.agent.sandbox import validate_python_artifacts
from app.domains.agent.service import AgentService
from app.domains.task.models import Task
from app.domains.task.service import TaskService
from app.workers.celery_app import celery_app


@celery_app.task(name="gapmind.run_agent", bind=True)
def run_agent_task(self, run_id: str) -> dict:
    del self
    db = SessionLocal()
    try:
        return AgentService(db).execute(run_id)
    finally:
        db.close()


def spawn_agent_task(run_id: str) -> str:
    return str(run_agent_task.delay(run_id).id)


@celery_app.task(name="gapmind.validate_agent_code", bind=True)
def validate_agent_code_task(self, task_id: str) -> dict:
    del self
    db = SessionLocal()
    try:
        task_service = TaskService(db)
        task = task_service.get(task_id)
        task_service.transition(task.id, "running", progress=0.1)
        run = db.get(AgentRun, str((task.payload or {}).get("agent_run_id") or ""))
        if run is None:
            raise RuntimeError("Agent run not found")
        artifacts = list(db.scalars(select(AgentArtifact).where(AgentArtifact.run_id == run.id, AgentArtifact.is_deleted.is_(False))))
        result = validate_python_artifacts(artifacts)
        for artifact in artifacts:
            if artifact.artifact_type == "code":
                artifact.validation_status = result["status"]
        run_result = dict(run.result or {})
        run_result["validation"] = result
        run.result = run_result
        if result["status"] == "failed":
            task_service.transition(task.id, "failed", progress=1.0, error=result.get("output", "validation failed"))
        else:
            task_service.transition(task.id, "succeeded", progress=1.0, result=result)
        db.commit()
        return result
    except Exception as exc:
        db.rollback()
        task = db.get(Task, task_id)
        if task and task.status in {"queued", "running"}:
            if task.status == "queued":
                TaskService(db).transition(task.id, "running", progress=0.1)
            TaskService(db).transition(task.id, "failed", error=str(exc))
        raise
    finally:
        db.close()


def spawn_agent_validation_task(task_id: str) -> str:
    return str(validate_agent_code_task.delay(task_id).id)

