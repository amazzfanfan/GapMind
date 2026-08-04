"""Export the current FastAPI OpenAPI schema to a JSON file.

This is the source of truth for the frontend's TypeScript types. Run from
the backend root:

    .venv/Scripts/python.exe scripts/export_openapi.py

The output lives at ``backend/openapi.json`` and is consumed by
``openapi-typescript`` (see ``frontend/package.json`` script
``gen:api-types``).

We deliberately don't import anything that touches the database here:
``app.openapi()`` only walks the registered routes, so the SQLite engine
fixture from tests isn't needed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make ``app`` importable when the script is launched directly via
# ``python scripts/export_openapi.py`` (without ``-m``).
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.main import app  # noqa: E402


def main() -> int:
    schema = app.openapi()
    target = Path(__file__).resolve().parent.parent / "openapi.json"
    target.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    route_count = len(schema.get("paths", {}))
    print(f"Wrote {target} ({route_count} routes, {target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())