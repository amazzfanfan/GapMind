"""Extraction pipeline sub-modules.

Lifted out of ``workers/tasks/extract_knowledge.py`` so each concern can be
unit-tested in isolation and so the worker file shrinks to a thin Celery
entry point. See ``S7`` in ``docs/architecture-refactor-plan-2026-08-04.md``.
"""
