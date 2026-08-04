"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Header
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


# Session factory is created lazily in db.session; re-exported here for deps.
# Importing here would create a circular import, so we import inside the function.
def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a SQLAlchemy session."""
    from app.db.session import SessionLocal

    session_factory: sessionmaker[Session] = SessionLocal
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def get_settings_dep() -> "settings.__class__":  # type: ignore[valid-type]
    """FastAPI dependency returning the cached Settings instance."""
    return settings


def get_current_user(
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
) -> str:
    """Resolve the acting user identity from the ``X-User-ID`` header.

    The MVP is single-user, so the header is optional and defaults to
    ``"user"``. Plumbing this through now means swapping in real auth
    later only touches this dependency — every downstream service already
    reads the actor from the request scope.
    """
    return x_user_id or "user"
