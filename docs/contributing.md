# Contributing notes (GapMind)

## Frontend types — never hand-write backend schemas

All TypeScript types that mirror a backend Pydantic schema **must** be
derived from `frontend/src/api/types/api.gen.ts`, which is generated from
the FastAPI OpenAPI schema.

```bash
# After touching a Pydantic model on the backend:
cd backend && .venv/Scripts/python.exe scripts/export_openapi.py
cd ../frontend && npm run gen:api-types
# Or both steps in one go from frontend/:
npm run gen:api
```

The thin re-export modules in `frontend/src/api/types/` (`domain.ts`,
`knowledge.ts`, `workspace.ts`) are the **only** place where types should
be aliased for readability. They must not redefine fields or invent new
ones — if a field is missing, add it to the backend Pydantic schema and
regenerate.

Rationale: hand-written types drift (see `docs/architecture-review-2026-08-02.md`
§P0-2). The codegen pipeline is the single source of truth.

## Backend routers — never translate domain exceptions inline

Domain exceptions raised by services are translated into HTTP responses by
the central dispatcher in `backend/app/core/exception_handlers.py`. To map
a new exception:

1. Define the exception class next to the service that raises it.
2. Add an entry to `EXCEPTION_REGISTRY` (or a special-case branch in
   `_resolve_status` if the status code or `retryable` flag depends on
   runtime data, like `DiscoverGateError.code`).
3. Register the exception class in `register_exception_handlers`.

Do **not** wrap a `try/except` block around the service call inside the
router just to convert an exception into an `HTTPException` — let it
propagate and rely on the central handler. This is the constraint that
made `chat/router.py` shrink by 50 lines and `paper/router.py` by 75.