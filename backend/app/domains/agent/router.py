"""Workspace-scoped Agent API."""

from __future__ import annotations

import io
import zipfile

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.domains.agent.schemas import (
    AgentConfirmResponse,
    AgentRunCreate,
    AgentRunDetail,
    AgentRunListResponse,
    AgentRunRead,
)
from app.domains.agent.service import AgentService
from app.domains.agent.service import AgentInputError
from app.domains.task.models import Task
from app.domains.task.schemas import TaskRead
from app.workers.tasks.run_agent import spawn_agent_task, spawn_agent_validation_task


router = APIRouter(prefix="/workspaces/{workspace_id}/agent-runs", tags=["agent"])


def _service(db: Session = Depends(get_db)) -> AgentService:
    return AgentService(db)


def _detail(service: AgentService, workspace_id: str, run_id: str) -> AgentRunDetail:
    run, steps, artifacts = service.detail(workspace_id, run_id)
    data = AgentRunRead.model_validate(run).model_dump()
    return AgentRunDetail(**data, steps=steps, artifacts=artifacts)


@router.post("", response_model=AgentRunRead, status_code=status.HTTP_202_ACCEPTED)
def start_agent(
    workspace_id: str,
    payload: AgentRunCreate,
    service: AgentService = Depends(_service),
) -> AgentRunRead:
    run = service.start(
        workspace_id,
        agent_type=payload.agent_type,
        prompt=payload.prompt,
        conversation_id=payload.conversation_id,
        input_payload=payload.input,
    )
    try:
        celery_id = spawn_agent_task(run.id)
        task = service.db.get(Task, run.task_id)
        if task:
            task.celery_task_id = celery_id
            service.db.commit()
    except Exception as exc:
        service.mark_dispatch_failed(run.id, str(exc))
        raise
    return AgentRunRead.model_validate(run)


@router.get("", response_model=AgentRunListResponse)
def list_agents(
    workspace_id: str,
    conversation_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: AgentService = Depends(_service),
) -> AgentRunListResponse:
    items, total = service.list(
        workspace_id,
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
    )
    return AgentRunListResponse(
        items=[AgentRunRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}", response_model=AgentRunDetail)
def get_agent(workspace_id: str, run_id: str, service: AgentService = Depends(_service)) -> AgentRunDetail:
    return _detail(service, workspace_id, run_id)


@router.post("/{run_id}/cancel", response_model=AgentRunRead)
def cancel_agent(workspace_id: str, run_id: str, service: AgentService = Depends(_service)) -> AgentRunRead:
    return AgentRunRead.model_validate(service.cancel(workspace_id, run_id))


@router.post("/{run_id}/confirm", response_model=AgentConfirmResponse)
def confirm_agent(workspace_id: str, run_id: str, service: AgentService = Depends(_service)) -> AgentConfirmResponse:
    run, plan = service.confirm(workspace_id, run_id)
    return AgentConfirmResponse(
        run=_detail(service, workspace_id, run.id),
        research_plan_id=plan.id if plan else None,
    )


@router.post("/{run_id}/validate", response_model=TaskRead, status_code=status.HTTP_202_ACCEPTED)
def validate_agent_code(workspace_id: str, run_id: str, service: AgentService = Depends(_service)) -> TaskRead:
    task = service.request_code_validation(workspace_id, run_id)
    task.celery_task_id = spawn_agent_validation_task(task.id)
    service.db.commit()
    service.db.refresh(task)
    return TaskRead.model_validate(task)


@router.get("/{run_id}/artifacts/{artifact_id}")
def download_artifact(workspace_id: str, run_id: str, artifact_id: str, service: AgentService = Depends(_service)) -> Response:
    artifact = service.artifact(workspace_id, run_id, artifact_id)
    return Response(
        content=artifact.content,
        media_type=artifact.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.filename.split("/")[-1]}"'},
    )


@router.get("/{run_id}/bundle")
def download_bundle(workspace_id: str, run_id: str, service: AgentService = Depends(_service)) -> Response:
    _, _, artifacts = service.detail(workspace_id, run_id)
    code = [item for item in artifacts if item.artifact_type == "code"]
    if not code:
        raise AgentInputError("该运行没有代码产物")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for artifact in code:
            archive.writestr(artifact.filename, artifact.content)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="gapmind-agent-{run_id[:8]}.zip"'},
    )
