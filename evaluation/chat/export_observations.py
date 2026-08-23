"""Export saved Workspace Chat answers for offline QA review.

This is a read-only exporter. It does not call an LLM, access Milvus, create
tasks, or mutate the workspace. Human verdicts are intentionally left empty.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
for import_root in (REPO_ROOT, BACKEND_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.domains.chat.models import ChatConversation, ChatMessage, ChatMessageEvidence
from evaluation.chat.gold_set import (
    ChatQAObservation,
    ChatQAObservationSet,
    EvidenceSnapshot,
    SourceSnapshot,
)


def _parse_selection(values: list[str]) -> list[tuple[str, str]]:
    selections: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value in values:
        query_id, separator, message_id = value.partition("=")
        if not separator or not query_id.strip() or not message_id.strip():
            raise ValueError(f"invalid selection {value!r}; expected query_id=message_id")
        query_id = query_id.strip()
        message_id = message_id.strip()
        if query_id in seen:
            raise ValueError(f"duplicate query_id: {query_id}")
        seen.add(query_id)
        selections.append((query_id, message_id))
    if not selections:
        raise ValueError("at least one query_id=message_id selection is required")
    return selections


def export_observations(
    workspace_id: str,
    case_id: str,
    selections: list[tuple[str, str]],
    *,
    include_message_ids: bool = False,
) -> ChatQAObservationSet:
    db = SessionLocal()
    try:
        observations: list[ChatQAObservation] = []
        for query_id, message_id in selections:
            message = db.scalar(
                select(ChatMessage)
                .join(ChatConversation, ChatConversation.id == ChatMessage.conversation_id)
                .where(
                    ChatMessage.id == message_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.status == "completed",
                    ChatConversation.workspace_id == workspace_id,
                    ChatConversation.is_deleted.is_(False),
                )
            )
            if message is None:
                raise ValueError(
                    f"message {message_id} is not a completed assistant message in workspace "
                    f"{workspace_id}"
                )

            evidence_rows = db.scalars(
                select(ChatMessageEvidence)
                .where(ChatMessageEvidence.message_id == message.id)
                .order_by(ChatMessageEvidence.rank)
            ).all()
            evidence = [
                EvidenceSnapshot(
                    rank=row.rank,
                    paper_ref=row.paper_title or row.paper_id or row.id,
                )
                for row in evidence_rows
            ]
            sources: list[SourceSnapshot] = []
            for source in message.source_manifest or []:
                source_type = source.get("source_type")
                if source_type == "paper":
                    continue
                if source_type not in {"plan", "report", "code_draft"}:
                    raise ValueError(
                        f"message {message.id} contains unsupported source type {source_type!r}"
                    )
                sources.append(
                    SourceSnapshot(
                        marker=source["marker"],
                        source_type=source_type,
                        title=source.get("title") or source.get("label") or source["marker"],
                    )
                )

            observations.append(
                ChatQAObservation(
                    query_id=query_id,
                    message_id=message.id if include_message_ids else None,
                    answer_text=message.content,
                    grounding_status=message.grounding_status,
                    evidence=evidence,
                    sources=sources,
                    human_verdict=None,
                )
            )
        return ChatQAObservationSet(gold_case_id=case_id, observations=observations)
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument(
        "--select",
        action="append",
        required=True,
        metavar="QUERY_ID=MESSAGE_ID",
        help="one saved assistant message per draft query; repeat for multiple samples",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--include-message-ids",
        action="store_true",
        help="keep local message ids for audit; omit by default for anonymized snapshots",
    )
    args = parser.parse_args()

    try:
        selections = _parse_selection(args.select)
        snapshot = export_observations(
            args.workspace_id,
            args.case_id,
            selections,
            include_message_ids=args.include_message_ids,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Exported {len(snapshot.observations)} observations to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
