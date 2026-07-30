"""Discover Agent HTTP API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.domains.discover.schemas import (
    ConfirmRequest,
    DecisionRequest,
    DiscoverRequest,
    DiscoverResponse,
    DiscoverRunCreateRequest,
    DiscoverRunCreateResponse,
    DiscoverRunDetail,
    DiscoverRunRead,
    EditConfirmRequest,
    ExternalSelectionRequest,
    OpportunityDetail,
    OpportunityEvidenceRead,
    OpportunityListResponse,
    OpportunityVersionRead,
    PlanCreateResponse,
    ResearchOpportunityListResponse,
    ResearchOpportunityRead,
    ResearchPlanRead,
)
from app.domains.discover.service import (
    DiscoverGateError,
    DiscoverInputError,
    DiscoverRunNotFoundError,
    DiscoverService,
    InvalidOpportunityTransition,
    OpportunityNotFoundError,
    OpportunityVersionConflict,
)
from app.domains.task.schemas import TaskCreate
from app.domains.task.service import TaskService
from app.domains.workspace.service import WorkspaceNotFoundError, WorkspaceService

router = APIRouter(prefix="/workspaces/{workspace_id}/discover", tags=["discover"])


def _service(db: Session = Depends(get_db)) -> DiscoverService:
    return DiscoverService(db)


def _workspace(db: Session, workspace_id: str) -> None:
    try:
        WorkspaceService(db).get(workspace_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"error": "workspace_not_found", "message": str(exc)}) from exc


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail={"error": "discover_not_found", "message": str(exc)})


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"error": code, "message": message, "retryable": False})


@router.post("/runs", response_model=DiscoverRunCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def create_run(
    workspace_id: str,
    payload: DiscoverRunCreateRequest,
    service: DiscoverService = Depends(_service),
    db: Session = Depends(get_db),
) -> DiscoverRunCreateResponse:
    _workspace(db, workspace_id)
    try:
        run, task_id = service.create_run(workspace_id, payload)
        from app.workers.tasks.run_discover import spawn_discover_task

        celery_id = spawn_discover_task(run.id)
        task = TaskService(db).get(task_id)
        task.celery_task_id = celery_id
        db.commit()
    except (DiscoverInputError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"error": "discover_preflight_failed", "message": str(exc), "retryable": False}) from exc
    except Exception as exc:
        # The run is already durable. Marking the task failed prevents a UI
        # from showing an eternal spinner when Redis/Celery is unavailable.
        raise HTTPException(status_code=503, detail={"error": "discover_worker_unavailable", "message": "Discover worker is unavailable; start Redis and Celery, then retry.", "retryable": True}) from exc
    return DiscoverRunCreateResponse(run_id=run.id, task_id=task_id, status=run.status)


@router.get("/runs", response_model=dict)
def list_runs(
    workspace_id: str,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: DiscoverService = Depends(_service),
    db: Session = Depends(get_db),
) -> dict:
    _workspace(db, workspace_id)
    items, total = service.list_runs(workspace_id, status_filter=status_filter, limit=limit, offset=offset)
    return {"items": [DiscoverRunRead.model_validate(item) for item in items], "total": total, "limit": limit, "offset": offset}


@router.get("/runs/{run_id}", response_model=DiscoverRunDetail)
def get_run(workspace_id: str, run_id: str, service: DiscoverService = Depends(_service), db: Session = Depends(get_db)) -> DiscoverRunDetail:
    _workspace(db, workspace_id)
    try:
        data = service.run_detail(workspace_id, run_id)
    except DiscoverRunNotFoundError as exc:
        raise _not_found(exc) from exc
    return DiscoverRunDetail(
        **DiscoverRunRead.model_validate(data["run"]).model_dump(),
        external_candidates=[item for item in data["external_candidates"]],
        opportunities=[ResearchOpportunityRead.model_validate(item) for item in data["opportunities"]],
    )


@router.post("/runs/{run_id}/external-selection", response_model=DiscoverRunRead)
def select_external(workspace_id: str, run_id: str, payload: ExternalSelectionRequest, service: DiscoverService = Depends(_service), db: Session = Depends(get_db)) -> DiscoverRunRead:
    _workspace(db, workspace_id)
    try:
        run = service.select_external(workspace_id, run_id, payload.candidate_ids)
        from app.workers.tasks.run_discover import spawn_discover_task

        celery_id = spawn_discover_task(run.id)
        if run.task_id:
            task = TaskService(db).get(run.task_id)
            task.celery_task_id = celery_id
            db.commit()
    except DiscoverRunNotFoundError as exc:
        raise _not_found(exc) from exc
    except DiscoverInputError as exc:
        raise HTTPException(status_code=422, detail={"error": "external_selection_invalid", "message": str(exc)}) from exc
    return DiscoverRunRead.model_validate(run)


@router.post("/runs/{run_id}/cancel", response_model=DiscoverRunRead)
def cancel_run(workspace_id: str, run_id: str, service: DiscoverService = Depends(_service), db: Session = Depends(get_db)) -> DiscoverRunRead:
    _workspace(db, workspace_id)
    try:
        return DiscoverRunRead.model_validate(service.cancel_run(workspace_id, run_id))
    except DiscoverRunNotFoundError as exc:
        raise _not_found(exc) from exc
    except InvalidOpportunityTransition as exc:
        raise _conflict("invalid_discover_run_transition", str(exc)) from exc


@router.get("/opportunities", response_model=OpportunityListResponse)
def list_opportunities(workspace_id: str, status_filter: str | None = Query(None, alias="status"), run_id: str | None = None, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), service: DiscoverService = Depends(_service), db: Session = Depends(get_db)) -> OpportunityListResponse:
    _workspace(db, workspace_id)
    items, total = service.list_opportunities(workspace_id, status_filter=status_filter, run_id=run_id, limit=limit, offset=offset)
    return OpportunityListResponse(items=[ResearchOpportunityRead.model_validate(item) for item in items], total=total, limit=limit, offset=offset)


@router.get("/opportunities/{opportunity_id}", response_model=OpportunityDetail)
def get_opportunity(workspace_id: str, opportunity_id: str, service: DiscoverService = Depends(_service), db: Session = Depends(get_db)) -> OpportunityDetail:
    _workspace(db, workspace_id)
    try:
        data = service.opportunity_detail(workspace_id, opportunity_id)
    except OpportunityNotFoundError as exc:
        raise _not_found(exc) from exc
    return OpportunityDetail(
        opportunity=ResearchOpportunityRead.model_validate(data["opportunity"]),
        current_version=OpportunityVersionRead.model_validate(data["current_version"]) if data["current_version"] else None,
        versions=[OpportunityVersionRead.model_validate(item) for item in data["versions"]],
        evidence=[OpportunityEvidenceRead.model_validate(item) for item in data["evidence"]],
        decisions=data["decisions"],
        plan=ResearchPlanRead.model_validate(data["plan"]) if data["plan"] else None,
    )


@router.get("/opportunities/{opportunity_id}/versions", response_model=list[OpportunityVersionRead])
def list_versions(workspace_id: str, opportunity_id: str, service: DiscoverService = Depends(_service)) -> list[OpportunityVersionRead]:
    try:
        return [OpportunityVersionRead.model_validate(item) for item in service.versions(workspace_id, opportunity_id)]
    except OpportunityNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/opportunities/{opportunity_id}/confirm", response_model=ResearchOpportunityRead)
def confirm(workspace_id: str, opportunity_id: str, payload: ConfirmRequest, service: DiscoverService = Depends(_service)) -> ResearchOpportunityRead:
    try:
        return ResearchOpportunityRead.model_validate(service.confirm(workspace_id, opportunity_id, payload.version_id, payload.note))
    except OpportunityNotFoundError as exc: raise _not_found(exc) from exc
    except (OpportunityVersionConflict, InvalidOpportunityTransition) as exc: raise _conflict("opportunity_version_conflict", str(exc)) from exc
    except DiscoverGateError as exc: raise HTTPException(status_code=422, detail={"error": exc.code, "message": str(exc), "retryable": False}) from exc


@router.patch("/opportunities/{opportunity_id}", response_model=ResearchOpportunityRead)
def edit_confirm(workspace_id: str, opportunity_id: str, payload: EditConfirmRequest, service: DiscoverService = Depends(_service)) -> ResearchOpportunityRead:
    try:
        return ResearchOpportunityRead.model_validate(service.edit_confirm(workspace_id, opportunity_id, payload.base_version_id, payload.changes, payload.note))
    except OpportunityNotFoundError as exc: raise _not_found(exc) from exc
    except OpportunityVersionConflict as exc: raise _conflict("opportunity_version_conflict", str(exc)) from exc
    except DiscoverGateError as exc: raise HTTPException(status_code=422, detail={"error": exc.code, "message": str(exc), "retryable": False}) from exc


@router.post("/opportunities/{opportunity_id}/reject", response_model=ResearchOpportunityRead)
def reject(workspace_id: str, opportunity_id: str, payload: DecisionRequest, service: DiscoverService = Depends(_service)) -> ResearchOpportunityRead:
    try: return ResearchOpportunityRead.model_validate(service.reject(workspace_id, opportunity_id, payload.note))
    except OpportunityNotFoundError as exc: raise _not_found(exc) from exc
    except InvalidOpportunityTransition as exc: raise _conflict("invalid_opportunity_transition", str(exc)) from exc


@router.post("/opportunities/{opportunity_id}/defer", response_model=ResearchOpportunityRead)
def defer(workspace_id: str, opportunity_id: str, payload: DecisionRequest, service: DiscoverService = Depends(_service)) -> ResearchOpportunityRead:
    try: return ResearchOpportunityRead.model_validate(service.defer(workspace_id, opportunity_id, payload.note, payload.defer_condition))
    except OpportunityNotFoundError as exc: raise _not_found(exc) from exc
    except InvalidOpportunityTransition as exc: raise _conflict("invalid_opportunity_transition", str(exc)) from exc


@router.post("/opportunities/{opportunity_id}/convert", response_model=PlanCreateResponse)
def convert(workspace_id: str, opportunity_id: str, service: DiscoverService = Depends(_service)) -> PlanCreateResponse:
    try: return PlanCreateResponse(plan=ResearchPlanRead.model_validate(service.convert_to_plan(workspace_id, opportunity_id)))
    except OpportunityNotFoundError as exc: raise _not_found(exc) from exc
    except DiscoverGateError as exc: raise HTTPException(status_code=422, detail={"error": exc.code, "message": str(exc), "retryable": False}) from exc


@router.post("/opportunities", response_model=DiscoverResponse)
def create_legacy_opportunity(workspace_id: str, payload: DiscoverRequest, service: DiscoverService = Depends(_service), db: Session = Depends(get_db)) -> DiscoverResponse:
    _workspace(db, workspace_id)
    try:
        opportunity, claim_text, similar, counter = service.discover(workspace_id, payload)
    except DiscoverInputError as exc:
        raise HTTPException(status_code=422, detail={"error": "invalid_discover_input", "message": str(exc)}) from exc
    return DiscoverResponse(opportunity=ResearchOpportunityRead.model_validate(opportunity), claim_text=claim_text, similar_work=similar, counter_evidence=counter)


@router.get("/opportunities-legacy", response_model=ResearchOpportunityListResponse)
def list_legacy_opportunities(workspace_id: str, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), service: DiscoverService = Depends(_service), db: Session = Depends(get_db)) -> ResearchOpportunityListResponse:
    _workspace(db, workspace_id)
    items, total = service.list_opportunities(workspace_id, status_filter=None, run_id=None, limit=limit, offset=offset)
    return ResearchOpportunityListResponse(items=[ResearchOpportunityRead.model_validate(item) for item in items], total=total, limit=limit, offset=offset)
