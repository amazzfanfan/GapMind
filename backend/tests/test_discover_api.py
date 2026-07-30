"""Contract tests for the durable Discover Agent API."""

from unittest.mock import patch

from fastapi.testclient import TestClient


def test_create_and_read_discover_run(client: TestClient) -> None:
    workspace = client.post("/api/v1/workspaces", json={"name": "Discover WS"}).json()
    with patch("app.workers.tasks.run_discover.spawn_discover_task", return_value="celery-test-id"):
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
    assert response.json()["detail"]["error"] == "discover_preflight_failed"
