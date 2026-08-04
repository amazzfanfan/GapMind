"""Shared error envelope helpers for the GapMind API.

All error responses emitted by exception handlers should go through
`error_envelope()` so that:

  * the wire format is stable: ``{"detail": {"error": code, "message": msg,
    "retryable": bool, **extra}}``
  * the Pydantic ``ErrorDetail`` / ``ErrorResponse`` schemas document the shape
    in OpenAPI for frontend codegen.

Frontend code (and the ``docs/architecture-refactor-plan-2026-08-04.md``
contract) reads errors as ``response.data.detail.error`` /
``.message`` / ``.retryable`` plus extra context fields such as
``conversation_id`` or ``assistant_message_id``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
    """Standard error detail payload.

    ``ConfigDict(extra="allow")`` keeps the schema open so domain-specific
    context (e.g. ``conversation_id``, ``run_id``) can ride along without
    forcing every handler to declare it on the model.
    """

    model_config = ConfigDict(extra="allow")

    error: str
    message: str
    retryable: bool = False


class ErrorResponse(BaseModel):
    """Standard error response envelope used by every 4xx/5xx handler."""

    detail: ErrorDetail


def error_envelope(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    """Build the standard error envelope dict.

    The shape mirrors the Pydantic ``ErrorResponse`` model above; keeping
    them aligned (by hand) is the contract that lets the frontend write a
    single interceptor.
    """
    detail: dict[str, Any] = {
        "error": code,
        "message": message,
        "retryable": retryable,
    }
    detail.update(extra)
    return {"detail": detail}