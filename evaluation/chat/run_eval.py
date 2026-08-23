"""Offline runner for the Workspace Chat QA Gold Set.

It accepts a human-authored Gold Set and observations exported from persisted
Chat messages.  It never sends prompts, calls an LLM, or changes database
state.  This separates reproducible QA scoring from expensive live replay.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
for path in (str(BACKEND_DIR), str(REPO_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from evaluation.chat.gold_set import ChatQAGoldSet, ChatQAObservationSet  # noqa: E402
from evaluation.chat.metrics import build_report  # noqa: E402


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score saved Workspace Chat answers offline.")
    parser.add_argument("--gold", type=Path, required=True, help="Path to a Chat QA Gold Set JSON file.")
    parser.add_argument(
        "--observations",
        type=Path,
        required=True,
        help="Path to saved Chat answer observations; no live Chat call is made.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON report path.")
    args = parser.parse_args(argv)

    try:
        gold = ChatQAGoldSet.model_validate(_load_json(args.gold))
        observations = ChatQAObservationSet.model_validate(_load_json(args.observations))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"Invalid Chat QA input: {exc}", file=sys.stderr)
        return 2

    if observations.gold_case_id != gold.case_id:
        print(
            "Observation gold_case_id does not match the supplied Gold Set: "
            f"{observations.gold_case_id!r} != {gold.case_id!r}",
            file=sys.stderr,
        )
        return 2

    report = build_report(gold, observations)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(rendered)

    return 0 if report["summary"]["mechanical_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
