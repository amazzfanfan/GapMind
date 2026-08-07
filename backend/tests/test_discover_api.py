"""Contract tests for the durable Discover Agent API."""

from datetime import datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.domains.discover.models import DiscoverRun, ResearchOpportunity


def test_create_and_read_discover_run(client: TestClient) -> None:
    workspace = client.post("/api/v1/workspaces", json={"name": "Discover WS"}).json()
    with patch("app.domains.discover.router.spawn_discover_task", return_value="celery-test-id"):
        response = client.post(
            f"/api/v1/workspaces/{workspace['id']}/discover/runs",
            json={
                "input": {"topic": "Robust graph learning under distribution shift"},
                "scope": {"year_from": 2020, "year_to": 2026},
                "config": {"max_opportunities": 3, "top_k": 10},
            },
        )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["task_id"]

    runs = client.get(f"/api/v1/workspaces/{workspace['id']}/discover/runs")
    assert runs.status_code == 200, runs.text
    assert runs.json()["total"] == 1
    run_id = runs.json()["items"][0]["id"]

    detail = client.get(f"/api/v1/workspaces/{workspace['id']}/discover/runs/{run_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["input_topic"].startswith("Robust graph")
    assert detail.json()["external_candidates"] == []


def test_discover_run_validates_workspace_scope(client: TestClient) -> None:
    first = client.post("/api/v1/workspaces", json={"name": "A"}).json()
    second = client.post("/api/v1/workspaces", json={"name": "B"}).json()
    response = client.post(
        f"/api/v1/workspaces/{first['id']}/discover/runs",
        json={"input": {"topic": "topic", "paper_ids": [second['id']]}},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "discover_input_invalid"


def test_discover_run_delete_hides_history_and_preserves_run_outputs(
    client: TestClient,
    db_session: Session,
) -> None:
    workspace = client.post("/api/v1/workspaces", json={"name": "Delete Discover WS"}).json()
    with patch("app.domains.discover.router.spawn_discover_task", return_value="celery-test-id"):
        created = client.post(
            f"/api/v1/workspaces/{workspace['id']}/discover/runs",
            json={"input": {"topic": "Topic to delete"}},
        )
    assert created.status_code == 202, created.text
    run_id = created.json()["run_id"]

    run = db_session.get(DiscoverRun, run_id)
    assert run is not None
    run.status = "succeeded"
    db_session.commit()

    deleted = client.delete(f"/api/v1/workspaces/{workspace['id']}/discover/runs/{run_id}")
    assert deleted.status_code == 204, deleted.text

    history = client.get(f"/api/v1/workspaces/{workspace['id']}/discover/runs")
    assert history.status_code == 200, history.text
    assert history.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}

    detail = client.get(f"/api/v1/workspaces/{workspace['id']}/discover/runs/{run_id}")
    assert detail.status_code == 404, detail.text
    assert detail.json()["detail"]["error"] == "discover_run_not_found"


def test_active_discover_run_cannot_be_deleted(client: TestClient) -> None:
    workspace = client.post("/api/v1/workspaces", json={"name": "Active Delete Discover WS"}).json()
    with patch("app.domains.discover.router.spawn_discover_task", return_value="celery-test-id"):
        created = client.post(
            f"/api/v1/workspaces/{workspace['id']}/discover/runs",
            json={"input": {"topic": "Active topic"}},
        )
    assert created.status_code == 202, created.text

    response = client.delete(
        f"/api/v1/workspaces/{workspace['id']}/discover/runs/{created.json()['run_id']}"
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["error"] == "discover_run_deletion_conflict"


def test_pending_opportunity_filter_returns_authoritative_workspace_count(
    client: TestClient,
    db_session: Session,
) -> None:
    workspace = client.post("/api/v1/workspaces", json={"name": "Opportunity Count WS"}).json()
    db_session.add_all(
        [
            ResearchOpportunity(
                workspace_id=workspace["id"],
                title="Candidate opportunity",
                summary="Summary",
                rationale="Rationale",
                status="candidate",
            ),
            ResearchOpportunity(
                workspace_id=workspace["id"],
                title="Needs evidence opportunity",
                summary="Summary",
                rationale="Rationale",
                status="needs_more_evidence",
            ),
            ResearchOpportunity(
                workspace_id=workspace["id"],
                title="Confirmed opportunity",
                summary="Summary",
                rationale="Rationale",
                status="confirmed",
            ),
        ]
    )
    db_session.commit()

    with patch("app.domains.discover.router.spawn_discover_task", return_value="celery-test-id"):
        created_run = client.post(
            f"/api/v1/workspaces/{workspace['id']}/discover/runs",
            json={"input": {"topic": "Deleted run topic"}},
        )
    assert created_run.status_code == 202, created_run.text
    deleted_run = db_session.get(DiscoverRun, created_run.json()["run_id"])
    assert deleted_run is not None
    deleted_run.deleted_at = datetime.now(timezone.utc)
    db_session.add(
        ResearchOpportunity(
            workspace_id=workspace["id"],
            discover_run_id=deleted_run.id,
            title="Deleted run opportunity",
            summary="Summary",
            rationale="Rationale",
            status="candidate",
        )
    )
    db_session.commit()

    all_response = client.get(
        f"/api/v1/workspaces/{workspace['id']}/discover/opportunities",
        params={"limit": 100},
    )
    assert all_response.status_code == 200, all_response.text
    assert all_response.json()["total"] == 3

    response = client.get(
        f"/api/v1/workspaces/{workspace['id']}/discover/opportunities",
        params={"pending_only": "true", "limit": 1},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["items"][0]["status"] in {"candidate", "needs_more_evidence"}
