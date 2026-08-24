"""Task HTTP API router.

Endpoints:
  GET    /api/v1/workspaces/{wid}/tasks          list (filterable by status)
  GET    /api/v1/tasks/{tid}                     get one (workspace-scoped via row)
  POST   /api/v1/tasks/{tid}/cancel              request cancel
  POST   /api/v1/tasks/{tid}/resume              resume from waiting_for_user
  POST   /api/v1/tasks/{tid}/retry               re-queue a failed task

Task *creation* is not exposed via HTTP in Phase 1b - tasks are created by
the system (Phase 2 workers) when a user uploads a PDF or asks for an
opportunity discovery. Exposing creation here would invite users to spawn
arbitrary task types.

Domain exceptions raised here are translated into HTTP responses by the
central handler registered in ``app.core.exception_handlers``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, get_db
from app.domains.task.schemas import TaskListResponse, TaskRead
from app.domains.task.service import TaskService
from app.domains.workspace.service import WorkspaceService

router = APIRouter(tags=["task"])


def _get_task_service(db: Session = Depends(get_db)) -> TaskService:
    return TaskService(db)


def _get_workspace_service(db: Session = Depends(get_db)) -> WorkspaceService:
    return WorkspaceService(db)


class ResumeBody(BaseModel):
    decision: dict | None = None


def _assert_task_owner(
    task,
    *,
    workspace_service: WorkspaceService,
    user_id: str,
) -> None:
    """Fail closed for task rows that have no user-visible Workspace owner."""
    if not task.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "task_not_found",
                "message": "Task is not attached to an accessible workspace",
            },
        )
    workspace_service.get(task.workspace_id, actor_id=user_id)


@router.get(
    "/workspaces/{workspace_id}/tasks",
    response_model=TaskListResponse,
    response_model_exclude_unset=True,
)
def list_tasks(
    workspace_id: str,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: TaskService = Depends(_get_task_service),
    workspace_service: WorkspaceService = Depends(_get_workspace_service),
    user_id: str = Depends(get_current_user),
) -> TaskListResponse:
    workspace_service.get(workspace_id, actor_id=user_id)
    items, total = service.list(
        workspace_id=workspace_id,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
    )
    return TaskListResponse(
        items=[TaskRead.model_validate(t) for t in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/tasks/{task_id}",
    response_model=TaskRead,
    response_model_exclude_unset=True,
)
def get_task(
    task_id: str,
    service: TaskService = Depends(_get_task_service),
    workspace_service: WorkspaceService = Depends(_get_workspace_service),
    user_id: str = Depends(get_current_user),
) -> TaskRead:
    task = service.get(task_id)
    _assert_task_owner(task, workspace_service=workspace_service, user_id=user_id)
    return TaskRead.model_validate(task)


@router.post(
    "/tasks/{task_id}/cancel",
    response_model=TaskRead,
    response_model_exclude_unset=True,
)
def cancel_task(
    task_id: str,
    service: TaskService = Depends(_get_task_service),
    workspace_service: WorkspaceService = Depends(_get_workspace_service),
    user_id: str = Depends(get_current_user),
) -> TaskRead:
    task = service.get(task_id)
    _assert_task_owner(task, workspace_service=workspace_service, user_id=user_id)
    return TaskRead.model_validate(service.request_cancel(task_id))


@router.post(
    "/tasks/{task_id}/resume",
    response_model=TaskRead,
    response_model_exclude_unset=True,
)
def resume_task(
    task_id: str,
    body: ResumeBody,
    service: TaskService = Depends(_get_task_service),
    workspace_service: WorkspaceService = Depends(_get_workspace_service),
    user_id: str = Depends(get_current_user),
) -> TaskRead:
    task = service.get(task_id)
    _assert_task_owner(task, workspace_service=workspace_service, user_id=user_id)
    return TaskRead.model_validate(service.resume_from_user(task_id, decision=body.decision))


@router.post(
    "/tasks/{task_id}/retry",
    response_model=TaskRead,
    response_model_exclude_unset=True,
)
def retry_task(
    task_id: str,
    service: TaskService = Depends(_get_task_service),
    workspace_service: WorkspaceService = Depends(_get_workspace_service),
    user_id: str = Depends(get_current_user),
) -> TaskRead:
    task = service.get(task_id)
    _assert_task_owner(task, workspace_service=workspace_service, user_id=user_id)
    return TaskRead.model_validate(service.retry(task_id))
