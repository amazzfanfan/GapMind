"""Discover-domain exception hierarchy.

Centralising these classes makes them importable from anywhere in the
domain (router, service submodules, tests) without dragging the rest of
``service.py`` along. The mapping from class → HTTP status lives in
``app.core.exception_handlers``.
"""

from __future__ import annotations


class DiscoverInputError(Exception):
    """User-provided input is invalid (missing topic, malformed paper_ids, ...)."""


class DiscoverRunNotFoundError(Exception):
    """No DiscoverRun with the given id (or it belongs to a different workspace)."""


class DiscoverRunDeletionConflict(Exception):
    """A DiscoverRun cannot be deleted while its worker is still active."""


class OpportunityNotFoundError(Exception):
    """No ResearchOpportunity with the given id (or workspace mismatch)."""


class OpportunityVersionConflict(Exception):
    """Optimistic-lock conflict — caller's base_version_id is stale."""


class InvalidOpportunityTransition(Exception):
    """Tried to move an Opportunity to a status not reachable from the current one."""


class DiscoverGateError(Exception):
    """Evidence gate failed before confirmation; ``code`` drives the front-end hint.

    Examples: ``insufficient_full_text_evidence``, ``coverage_below_threshold``.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DiscoverRunCancelled(Exception):
    """Internal signal raised when a run has been cancelled mid-pipeline."""


__all__ = [
    "DiscoverInputError",
    "DiscoverRunDeletionConflict",
    "DiscoverRunNotFoundError",
    "OpportunityNotFoundError",
    "OpportunityVersionConflict",
    "InvalidOpportunityTransition",
    "DiscoverGateError",
    "DiscoverRunCancelled",
]
