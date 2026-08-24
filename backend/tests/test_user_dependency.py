"""Tests for the lightweight ``X-User-ID`` dependency.

The MVP is single-user, so the dependency falls back to ``"user"`` when
the header is absent. Wiring this in now means a future auth migration
only touches ``get_current_user``.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.deps import get_current_user


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/me")
    def me(user: str = Depends(get_current_user)):
        return {"user": user}

    return TestClient(app)


def test_get_current_user_defaults_when_header_missing() -> None:
    client = _client()
    response = client.get("/me")
    assert response.json() == {"user": "user"}


def test_get_current_user_resolves_header() -> None:
    client = _client()
    response = client.get("/me", headers={"X-User-ID": "alice"})
    assert response.json() == {"user": "alice"}


def test_get_current_user_handles_empty_header() -> None:
    """An empty ``X-User-ID`` is treated as 'no header' → fallback."""
    client = _client()
    response = client.get("/me", headers={"X-User-ID": ""})
    assert response.json() == {"user": "user"}


def test_get_current_user_accepts_configured_bearer_token(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "auth_required", True)
    monkeypatch.setattr(settings, "auth_tokens", "demo-token:alice")
    response = _client().get("/me", headers={"Authorization": "Bearer demo-token"})
    assert response.status_code == 200
    assert response.json() == {"user": "alice"}


def test_get_current_user_rejects_spoofed_header_outside_development(monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "auth_required", True)
    monkeypatch.setattr(settings, "auth_tokens", "demo-token:alice")
    response = _client().get("/me", headers={"X-User-ID": "alice"})
    assert response.status_code == 401
    assert response.json()["detail"]["error"] == "authentication_required"
