"""Discover Agent orchestration and opportunity workflow.

The service keeps the expensive external/LLM work outside HTTP transactions.
Runs are durable product objects; Celery is only the execution mechanism.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.artifact.models import Artifact
from app.domains.artifact.service import ArtifactService
from app.domains.discover.models import (
    DiscoverExternalCandidate,
    DiscoverRun,
    HumanDecision,
    OpportunityEvidence,
    OpportunityVersion,
    ResearchOpportunity,
    ResearchPlan,
)
from app.domains.discover.schemas import (
    DiscoverConfig,
    DiscoverInput,
    DiscoverRunCreateRequest,
    DiscoverScope,
)
from app.domains.knowledge.models import EvidenceSpan, KnowledgeItem
from app.domains.paper.models import Paper
from app.domains.paper.schemas import PaperCreate
from app.domains.paper.service import PaperService
from app.domains.retrieval.schemas import RetrievalResponse, RetrievalResultItem
from app.domains.retrieval.service import find_counter_evidence, find_similar_work, semantic_search
from app.domains.task.models import Task
from app.domains.task.schemas import TaskCreate
from app.domains.task.service import TaskService
from app.domains.timeline.service import TimelineService
from app.gateway.llm import get_llm_gateway
from app.gateway.semantic_scholar import SemanticScholarClient, SemanticScholarError

logger = get_logger(__name__)

S2_FIELDS = "paperId,externalIds,title,abstract,year,authors,openAccessPdf,url,publicationDate"
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "cancelled"}
WAITING_RUN_STATUSES = {"waiting_for_user", "waiting_for_fulltext"}
PIPELINE_PENDING_STATUSES = {"queued", "running", "waiting_for_user"}


class DiscoverInputError(Exception):
    pass


class DiscoverRunNotFoundError(Exception):
    pass


class OpportunityNotFoundError(Exception):
    pass


class OpportunityVersionConflict(Exception):
    pass


class InvalidOpportunityTransition(Exception):
    pass


class DiscoverGateError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DiscoverRunCancelled(Exception):
    """Internal control-flow signal used to stop a stale worker safely."""


class DiscoverService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.timeline = TimelineService(db)

    # ---------------------------------------------------------------- runs
    def create_run(
        self,
        workspace_id: str,
        request: DiscoverRunCreateRequest,
        *,
        trigger_type: str = "topic",
        parent_run_id: str | None = None,
    ) -> tuple[DiscoverRun, str | None]:
        claim = self._resolve_claim(workspace_id, request.input.claim_item_id)
        topic = (request.input.topic or "").strip() or (self._claim_text(claim) if claim else "")
        if not topic:
            raise DiscoverInputError("a topic or a valid claim is required")
        self._validate_papers(workspace_id, request.input.paper_ids)

        task = TaskService(self.db).create(
            TaskCreate(
                workspace_id=workspace_id,
                task_type="discover_agent",
                payload={"kind": "discover", "status": "queued"},
            )
        )
        run = DiscoverRun(
            id=str(uuid4()),
            workspace_id=workspace_id,
            task_id=task.id,
            parent_run_id=parent_run_id,
            trigger_type=trigger_type,
            input_topic=topic,
            input_claim_item_id=claim.id if claim else None,
            input_payload=request.input.model_dump(mode="json"),
            scope=request.scope.model_dump(mode="json"),
            config=request.config.model_dump(mode="json"),
            status="queued",
            stage="preflight",
            progress=0.0,
            verification_status="not_started",
            model_provider="deepseek",
            model_name="deepseek-chat",
            model_parameters={"temperature": 0.1, "max_tokens": 2200},
            stage_summaries={},
        )
        self.db.add(run)
        self.db.flush()
        task.payload = {**(task.payload or {}), "run_id": run.id}
        self.db.commit()
        self.db.refresh(run)
        self.timeline.record(
            workspace_id=workspace_id,
            event_type="discover.run_created",
            subject_type="discover_run",
            subject_id=run.id,
            actor="user",
            payload={"run_id": run.id, "task_id": task.id, "trigger_type": trigger_type},
        )
        return run, task.id

    def list_runs(self, workspace_id: str, *, status_filter: str | None, limit: int, offset: int) -> tuple[list[DiscoverRun], int]:
        base = select(DiscoverRun).where(DiscoverRun.workspace_id == workspace_id)
        if status_filter:
            base = base.where(DiscoverRun.status == status_filter)
        items = list(self.db.execute(base.order_by(DiscoverRun.created_at.desc()).limit(limit).offset(offset)).scalars())
        total = int(self.db.execute(select(func.count()).select_from(base.subquery())).scalar() or 0)
        return items, total

    def get_run(self, workspace_id: str, run_id: str) -> DiscoverRun:
        run = self.db.get(DiscoverRun, run_id)
        if run is None or run.workspace_id != workspace_id:
            raise DiscoverRunNotFoundError(run_id)
        return run

    def run_detail(self, workspace_id: str, run_id: str) -> dict[str, Any]:
        run = self.get_run(workspace_id, run_id)
        candidates = list(self.db.execute(select(DiscoverExternalCandidate).where(DiscoverExternalCandidate.discover_run_id == run.id).order_by(DiscoverExternalCandidate.rank)).scalars())
        opportunities = list(self.db.execute(select(ResearchOpportunity).where(ResearchOpportunity.discover_run_id == run.id, ResearchOpportunity.is_deleted.is_(False)).order_by(ResearchOpportunity.created_at)).scalars())
        return {"run": run, "external_candidates": candidates, "opportunities": opportunities}

    def cancel_run(self, workspace_id: str, run_id: str) -> DiscoverRun:
        run = self.get_run(workspace_id, run_id)
        if run.status in TERMINAL_RUN_STATUSES:
            raise InvalidOpportunityTransition(f"Run is already {run.status}")
        if run.task_id:
            TaskService(self.db).request_cancel(run.task_id)
        run.status = "cancelled"
        run.finished_at = datetime.now(timezone.utc)
        run.stage = "cancelled"
        self.db.commit()
        self.timeline.record(workspace_id=workspace_id, event_type="discover.run_cancelled", subject_type="discover_run", subject_id=run.id, payload={"run_id": run.id})
        return run

    def select_external(self, workspace_id: str, run_id: str, candidate_ids: list[str]) -> DiscoverRun:
        run = self.get_run(workspace_id, run_id)
        if run.status in {"cancelled", "succeeded"}:
            raise DiscoverInputError(f"Run is already {run.status}")
        rows = list(self.db.execute(select(DiscoverExternalCandidate).where(DiscoverExternalCandidate.discover_run_id == run.id, DiscoverExternalCandidate.id.in_(candidate_ids))).scalars())
        if len(rows) != len(set(candidate_ids)):
            raise DiscoverInputError("one or more external candidates do not belong to this run")
        protected_statuses = {"selected", "imported_pending_parse", "verified"}
        if any(row.verification_status in protected_statuses for row in rows):
            raise DiscoverInputError("one or more external candidates are already selected or verified")
        for row in rows:
            row.verification_status = "selected"
        run.status = "queued"
        run.stage = "fulltext_verification"
        run.progress = max(run.progress, 0.65)
        run.verification_status = "in_progress"
        run.stage_summaries = {**(run.stage_summaries or {}), "external_selection": {"selected": len(rows), "status": "queued"}}
        self.db.commit()
        if run.task_id:
            try:
                TaskService(self.db).resume_from_user(run.task_id, decision={"candidate_ids": candidate_ids})
            except Exception:
                pass
        return run

    def _external_candidate_state(self, run: DiscoverRun) -> dict[str, Any]:
        rows = list(
            self.db.execute(
                select(DiscoverExternalCandidate)
                .where(DiscoverExternalCandidate.discover_run_id == run.id)
                .order_by(DiscoverExternalCandidate.rank)
            ).scalars()
        )
        for row in rows:
            if row.imported_paper_id and row.verification_status in {
                "selected", "imported_pending_parse", "verification_failed"
            }:
                state = self._paper_pipeline_state(row.imported_paper_id)
                if state["ready"]:
                    row.verification_status = "verified"
                    row.evidence_level = "full_text"
                elif state["failed"]:
                    row.verification_status = "verification_failed"
                    row.snapshot_payload = {
                        **(row.snapshot_payload or {}),
                        "verification_error": state["error"],
                    }
                else:
                    row.verification_status = "imported_pending_parse"
        self.db.commit()
        return {
            "selected": sum(row.verification_status == "selected" for row in rows),
            "pending": sum(row.verification_status == "imported_pending_parse" for row in rows),
            "verified": sum(row.verification_status == "verified" for row in rows),
            "failed": sum(row.verification_status in {"no_pdf", "import_failed", "verification_failed"} for row in rows),
            "rows": rows,
        }

    def _wait_for_fulltext(self, run: DiscoverRun, state: dict[str, Any]) -> dict[str, Any]:
        self.db.refresh(run)
        if self._cancelled(run):
            return self._cancelled_result(run)
        pending = int(state.get("pending", 0))
        failed = int(state.get("failed", 0))
        if pending:
            run.status = "waiting_for_fulltext"
            run.stage = "fulltext_verification"
            run.progress = max(run.progress, 0.68)
            run.verification_status = "in_progress"
            summary = {
                "status": "waiting_for_fulltext",
                "pending": pending,
                "verified": int(state.get("verified", 0)),
                "failed": failed,
                "message": "Waiting for PDF parsing, knowledge extraction, and vector indexing.",
            }
        else:
            run.status = "waiting_for_user"
            run.stage = "external_selection"
            run.progress = max(run.progress, 0.62)
            run.verification_status = "failed" if failed else "incomplete"
            summary = {
                "status": "waiting_for_user",
                "pending": 0,
                "verified": int(state.get("verified", 0)),
                "failed": failed,
                "message": "Select another candidate or retry the failed full-text verification.",
            }
        run.stage_summaries = {**(run.stage_summaries or {}), "fulltext_verification": summary}
        self.db.commit()
        if run.task_id:
            try:
                TaskService(self.db).transition(run.task_id, "waiting_for_user", progress=run.progress)
            except Exception:
                pass
        return {
            "run_id": run.id,
            "status": run.status,
            "waiting_for_fulltext": pending > 0,
            "waiting_for_user": pending == 0,
            "verification": summary,
        }

    def _paper_pipeline_state(self, paper_id: str) -> dict[str, Any]:
        paper = self.db.get(Paper, paper_id)
        if paper is None or paper.is_deleted:
            return {"ready": False, "failed": True, "error": "Imported paper was deleted or not found."}
        if paper.parse_status in {"pending", "parsing"} or not paper.parsed_markdown_artifact_id:
            return {"ready": False, "failed": False, "error": "PDF parsing is still running."}
        if paper.parse_status == "failed":
            return {"ready": False, "failed": True, "error": "PDF parsing failed."}
        if paper.extract_status in {"pending", "extracting", "not_applicable"}:
            return {"ready": False, "failed": False, "error": "Knowledge extraction is still running."}
        if paper.extract_status == "failed":
            return {"ready": False, "failed": True, "error": "Knowledge extraction failed."}
        span_count = int(
            self.db.execute(
                select(func.count()).select_from(EvidenceSpan).where(EvidenceSpan.paper_id == paper.id)
            ).scalar()
            or 0
        )
        if span_count == 0:
            return {"ready": False, "failed": True, "error": "No EvidenceSpan was extracted from the imported paper."}
        embed_tasks = [
            task
            for task in self.db.execute(
                select(Task).where(Task.task_type == "embed_chunks").order_by(Task.updated_at.desc())
            ).scalars()
            if (task.payload or {}).get("paper_id") == paper.id
        ]
        latest_embed = embed_tasks[0] if embed_tasks else None
        if latest_embed is None or latest_embed.status in PIPELINE_PENDING_STATUSES:
            return {"ready": False, "failed": False, "error": "Vector indexing is still running."}
        if latest_embed.status == "failed":
            return {"ready": False, "failed": True, "error": latest_embed.error or "Vector indexing failed."}
        if latest_embed.status != "succeeded":
            return {"ready": False, "failed": False, "error": "Vector indexing has not completed."}
        return {"ready": True, "failed": False, "error": None}


    # -------------------------------------------------------------- worker
    def execute_run(self, run_id: str) -> dict[str, Any]:
        run = self.db.get(DiscoverRun, run_id)
        if run is None:
            raise DiscoverRunNotFoundError(run_id)
        if run.status in TERMINAL_RUN_STATUSES:
            return {"run_id": run.id, "status": run.status, "idempotent": True}
        task_service = TaskService(self.db)
        if self._cancelled(run):
            return {"run_id": run.id, "status": "cancelled", "idempotent": True}
        if run.task_id:
            task = task_service.get(run.task_id)
            if task.status == "queued":
                task_service.transition(task.id, "running")
            elif task.status in {"cancel_requested", "cancelled"}:
                return self._cancelled_result(run)
        run.status = "running"
        run.started_at = run.started_at or datetime.now(timezone.utc)
        self._stage(run, "preflight", 0.05)

        claim = self._resolve_claim(run.workspace_id, run.input_claim_item_id)
        claim_text = self._claim_text(claim) if claim else (run.input_topic or "")
        if not claim_text.strip():
            return self._fail_run(run, "discover_preflight_failed", "No usable topic or claim was provided")

        config = DiscoverConfig.model_validate(run.config or {})
        self._checkpoint(run)
        similar = self._workspace_similar(run, claim, claim_text, config)
        self._stage(run, "workspace_retrieval", 0.28, {"similar_work": len(similar.items)})
        self._checkpoint(run)
        self._stage(run, "similar_work", 0.34, {"items": len(similar.items), "status": similar.status})
        counter = self._workspace_counter(run, claim, claim_text, config)
        self._stage(run, "counter_evidence", 0.42, {"counter_evidence": len(counter.items), "status": counter.status})

        external = self._external_verify(run, claim_text)
        self._stage(run, "external_search", 0.58, {"external_candidates": external})
        self._checkpoint(run)
        candidate_state = self._external_candidate_state(run)
        selected = candidate_state["selected"]
        pending = candidate_state["pending"]
        verified = candidate_state["verified"]
        failed = candidate_state["failed"]
        if external and not selected and not pending and not verified and not failed:
            run.status = "waiting_for_user"
            run.stage = "external_selection"
            run.progress = 0.62
            run.verification_status = "incomplete"
            run.stage_summaries = {**(run.stage_summaries or {}), "external_selection": {"status": "waiting_for_user", "candidate_count": external}}
            self.db.commit()
            if run.task_id:
                try:
                    task_service.transition(run.task_id, "waiting_for_user", progress=run.progress)
                except Exception:
                    pass
            self.timeline.record(workspace_id=run.workspace_id, event_type="discover.external_input_requested", subject_type="discover_run", subject_id=run.id, actor="agent", payload={"run_id": run.id, "candidate_count": external})
            return {"run_id": run.id, "status": run.status, "waiting_for_user": True}
        if selected:
            self._import_selected_candidates(run)
            candidate_state = self._external_candidate_state(run)
            if candidate_state["pending"]:
                return self._wait_for_fulltext(run, candidate_state)
            if not candidate_state["verified"] and candidate_state["failed"]:
                return self._wait_for_fulltext(run, candidate_state)
            self._stage(run, "fulltext_verification", 0.68, {"selected": selected, "verified": candidate_state["verified"]})
        elif pending:
            return self._wait_for_fulltext(run, candidate_state)

        self._checkpoint(run)
        supporting = self._workspace_supporting(run, claim, claim_text, config)
        external_fulltext = self._external_fulltext(run, supporting)
        preliminary_gate = self._evidence_gate(
            run,
            candidate=None,
            supporting=supporting,
            counter=counter,
        )
        self._stage(run, "synthesis", 0.76, {"status": "running", "preliminary_gate": preliminary_gate})
        candidates = self._synthesize_candidates(
            run,
            claim_text,
            supporting,
            similar,
            counter,
            external_fulltext,
            preliminary_gate,
            config.max_opportunities,
        )
        self._checkpoint(run)
        created, final_gates = self._persist_candidates(
            run,
            claim,
            claim_text,
            supporting,
            similar,
            counter,
            external_fulltext,
            candidates,
        )
        run.status = "succeeded"
        run.stage = "saved"
        run.progress = 1.0
        run.verification_status = "complete" if any(gate["verified"] for gate in final_gates) else "incomplete"
        run.finished_at = datetime.now(timezone.utc)
        run.stage_summaries = {
            **(run.stage_summaries or {}),
            "saved": {"opportunities": len(created), "gates": final_gates},
        }
        self.db.commit()
        if run.task_id:
            try:
                task_service.transition(run.task_id, "succeeded", progress=1.0, result={"run_id": run.id, "opportunity_ids": [item.id for item in created]})
            except Exception:
                pass
        self.timeline.record(workspace_id=run.workspace_id, event_type="discover.run_completed", subject_type="discover_run", subject_id=run.id, actor="agent", payload={"run_id": run.id, "opportunities": len(created), "verification_status": run.verification_status})
        return {"run_id": run.id, "status": run.status, "opportunity_ids": [item.id for item in created]}

    def _checkpoint(self, run: DiscoverRun) -> None:
        """Refresh the run and stop this worker after a user cancellation."""
        self.db.refresh(run)
        if self._cancelled(run):
            raise DiscoverRunCancelled(run.id)

    @staticmethod
    def _cancelled(run: DiscoverRun) -> bool:
        return run.status == "cancelled"

    def _cancelled_result(self, run: DiscoverRun) -> dict[str, Any]:
        run.status = "cancelled"
        run.stage = "cancelled"
        run.finished_at = run.finished_at or datetime.now(timezone.utc)
        self.db.commit()
        return {"run_id": run.id, "status": "cancelled", "idempotent": True}

    def _stage(self, run: DiscoverRun, stage: str, progress: float, summary: dict[str, Any] | None = None) -> None:
        self.db.refresh(run)
        if self._cancelled(run):
            return
        run.stage = stage
        run.progress = progress
        run.stage_summaries = {**(run.stage_summaries or {}), stage: summary or {"status": "succeeded"}}
        self.db.commit()
        self.timeline.record(workspace_id=run.workspace_id, event_type="discover.stage_completed", subject_type="discover_run", subject_id=run.id, actor="agent", payload={"run_id": run.id, "stage": stage, "progress": progress, "summary": summary or {}})

    def _fail_run(self, run: DiscoverRun, code: str, message: str) -> dict[str, Any]:
        run.status = "failed"
        run.stage = "failed"
        run.error_code = code
        run.error_message = message
        run.finished_at = datetime.now(timezone.utc)
        self.db.commit()
        if run.task_id:
            try:
                TaskService(self.db).transition(run.task_id, "failed", error=message)
            except Exception:
                pass
        self.timeline.record(workspace_id=run.workspace_id, event_type="discover.run_failed", subject_type="discover_run", subject_id=run.id, payload={"run_id": run.id, "error_code": code, "message": message})
        return {"run_id": run.id, "status": "failed", "error_code": code}

    # ----------------------------------------------------------- retrieval
    def _workspace_similar(self, run: DiscoverRun, claim: KnowledgeItem | None, text: str, config: DiscoverConfig) -> RetrievalResponse:
        paper_id = claim.paper_id if claim else None
        if paper_id:
            return find_similar_work(run.workspace_id, paper_id, config.top_k, use_reranker=config.use_reranker, exclude_paper_ids={paper_id})
        return semantic_search(run.workspace_id, text, config.top_k, use_reranker=config.use_reranker)

    def _workspace_counter(self, run: DiscoverRun, claim: KnowledgeItem | None, text: str, config: DiscoverConfig) -> RetrievalResponse:
        if not config.include_counter_evidence:
            return self._empty_response(run.workspace_id, text, "counter_evidence")
        excluded = {claim.paper_id} if claim and claim.paper_id else set()
        return find_counter_evidence(run.workspace_id, text, config.top_k, use_reranker=config.use_reranker, use_judge=config.use_judge, exclude_paper_ids=excluded)

    def _external_verify(self, run: DiscoverRun, query: str) -> int:
        existing = int(self.db.execute(select(func.count()).select_from(DiscoverExternalCandidate).where(DiscoverExternalCandidate.discover_run_id == run.id)).scalar() or 0)
        if existing:
            rows = list(self.db.execute(select(DiscoverExternalCandidate).where(DiscoverExternalCandidate.discover_run_id == run.id)).scalars())
            self._external_candidate_state(run)
            return existing
        scope = DiscoverScope.model_validate(run.scope or {})
        year = None
        if scope.year_from is not None or scope.year_to is not None:
            year = f"{scope.year_from or ''}-{scope.year_to or ''}"
        try:
            raw = SemanticScholarClient().search(query=query[:200], fields=S2_FIELDS, sort="relevance", limit=min(20, int((run.config or {}).get("top_k", 10))), year=year)
        except SemanticScholarError as exc:
            run.verification_status = "failed"
            run.stage_summaries = {**(run.stage_summaries or {}), "external_search": {"status": "failed", "error": str(exc), "retryable": exc.status_code in {429, 502, 504}, "executed": False}}
            self.db.commit()
            logger.warning("discover.external_search_failed", run_id=run.id, error=str(exc))
            return 0
        rows: list[DiscoverExternalCandidate] = []
        for rank, item in enumerate(raw.get("data") or [], start=1):
            if not isinstance(item, dict) or not item.get("paperId") or not item.get("title"):
                continue
            authors = [a.get("name", "") for a in item.get("authors") or [] if isinstance(a, dict) and a.get("name")]
            row = DiscoverExternalCandidate(
                id=str(uuid4()), discover_run_id=run.id, query=query[:200], rank=rank,
                external_paper_id=str(item["paperId"]), title=str(item["title"]), authors=authors,
                year=item.get("year") if isinstance(item.get("year"), int) else None,
                abstract=item.get("abstract") if isinstance(item.get("abstract"), str) else None,
                open_access_pdf=item.get("openAccessPdf") if isinstance(item.get("openAccessPdf"), dict) else None,
                role=self._external_role(query, item), role_confidence=0.35,
                evidence_level="metadata_only", verification_status="unverified", snapshot_payload=item,
            )
            rows.append(row)
        self.db.add_all(rows)
        run.verification_status = "in_progress" if rows else "incomplete"
        run.stage_summaries = {
            **(run.stage_summaries or {}),
            "external_search": {
                "status": "succeeded" if rows else "succeeded_empty",
                "executed": True,
                "candidate_count": len(rows),
            },
        }
        self.db.commit()
        return len(rows)

    def _import_selected_candidates(self, run: DiscoverRun) -> None:
        """Best-effort import of user-selected OA PDFs.

        Import is deliberately explicit: metadata-only candidates never become
        full-text evidence. Parsing/indexing remains in the existing worker
        pipeline and the candidate stays visibly pending until it completes.
        """
        client = SemanticScholarClient()
        rows = list(self.db.execute(select(DiscoverExternalCandidate).where(DiscoverExternalCandidate.discover_run_id == run.id, DiscoverExternalCandidate.verification_status == "selected")).scalars())
        for row in rows:
            if row.imported_paper_id:
                self._ensure_paper_pipeline(run.workspace_id, row.imported_paper_id)
                continue
            raw = row.snapshot_payload or {}
            pdf = row.open_access_pdf or {}
            pdf_url = pdf.get("url") if isinstance(pdf, dict) else None
            if not isinstance(pdf_url, str) or not pdf_url.strip():
                external_ids = raw.get("externalIds") if isinstance(raw.get("externalIds"), dict) else {}
                arxiv_id = external_ids.get("ArXiv") or external_ids.get("ARXIV")
                if isinstance(arxiv_id, str) and arxiv_id.strip():
                    arxiv_id = arxiv_id.removeprefix("arXiv:").removesuffix(".pdf").strip()
                    pdf_url = f"https://arxiv.org/pdf/{quote(arxiv_id, safe='/')}"
            if not isinstance(pdf_url, str) or not pdf_url.strip():
                row.verification_status = "no_pdf"
                continue
            try:
                content = client.download_pdf(pdf_url.strip())
                paper_service = PaperService(self.db)
                paper = paper_service.find_by_external_paper_id(workspace_id=run.workspace_id, external_paper_id=row.external_paper_id)
                if paper is None:
                    paper = paper_service.create_from_metadata(workspace_id=run.workspace_id, payload=PaperCreate(title=row.title, authors=row.authors, year=row.year, abstract=row.abstract), source="semantic_scholar", external_paper_id=row.external_paper_id)
                if paper.primary_artifact_id is None:
                    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", row.title)[:120] or row.external_paper_id
                    paper = paper_service.attach_pdf_to_existing(workspace_id=run.workspace_id, paper_id=paper.id, filename=f"{filename}.pdf", content=content, mime_type="application/pdf")
                row.imported_paper_id = paper.id
                row.verification_status = "imported_pending_parse"
                row.evidence_level = "metadata_only"
            except (SemanticScholarError, ValueError) as exc:
                row.verification_status = "import_failed"
                row.snapshot_payload = {**raw, "import_error": str(exc)[:500]}
        self.db.commit()

    def _ensure_paper_pipeline(self, workspace_id: str, paper_id: str) -> None:
        """Safely restart only the missing/failed existing pipeline stage."""
        paper = self.db.get(Paper, paper_id)
        if paper is None or paper.is_deleted:
            return
        active = list(
            self.db.execute(
                select(Task).where(
                    Task.workspace_id == workspace_id,
                    Task.status.in_(PIPELINE_PENDING_STATUSES),
                    Task.is_deleted.is_(False),
                )
            ).scalars()
        )

        def has_active(task_type: str) -> bool:
            return any(
                task.task_type == task_type
                and (task.payload or {}).get("paper_id") == paper_id
                for task in active
            )

        if paper.primary_artifact_id and paper.parse_status in {"pending", "failed", "parsing"} and not has_active("parse_pdf"):
            from app.workers.tasks.parse_pdf import spawn_parse_pdf_task

            paper.parse_status = "pending"
            self.db.commit()
            spawn_parse_pdf_task(self.db, paper_id, workspace_id)
            return
        if paper.parsed_markdown_artifact_id and paper.extract_status in {"pending", "failed", "extracting", "not_applicable"} and not has_active("extract_knowledge"):
            from app.workers.tasks.extract_knowledge import spawn_extract_knowledge

            spawn_extract_knowledge(self.db, paper_id, workspace_id)
        if paper.parsed_text_artifact_id and not has_active("embed_chunks"):
            latest = next(
                (
                    task
                    for task in self.db.execute(
                        select(Task).where(Task.task_type == "embed_chunks").order_by(Task.updated_at.desc())
                    ).scalars()
                    if (task.payload or {}).get("paper_id") == paper_id
                ),
                None,
            )
            if latest is None or latest.status == "failed":
                from app.workers.tasks.embed_chunks import spawn_embed_chunks

                spawn_embed_chunks(self.db, paper_id, workspace_id)

    @staticmethod
    def _external_role(query: str, item: dict[str, Any]) -> str:
        haystack = f"{item.get('title', '')} {item.get('abstract', '')}".lower()
        tokens = [token for token in re.findall(r"[a-z0-9]{4,}", query.lower()) if token not in {"with", "from", "under", "using"}]
        overlap = sum(token in haystack for token in tokens)
        return "similar" if overlap >= max(1, len(tokens) // 4) else "unknown"

    def _workspace_supporting(
        self,
        run: DiscoverRun,
        claim: KnowledgeItem | None,
        text: str,
        config: DiscoverConfig,
    ) -> RetrievalResponse:
        excluded = {claim.paper_id} if claim and claim.paper_id else set()
        response = semantic_search(run.workspace_id, text, config.top_k * 3, use_reranker=config.use_reranker)
        if response.status == "failed":
            return response.model_copy(update={"purpose": "supporting_evidence"})
        imported_ids = {
            row.imported_paper_id
            for row in self.db.execute(
                select(DiscoverExternalCandidate).where(
                    DiscoverExternalCandidate.discover_run_id == run.id,
                    DiscoverExternalCandidate.verification_status == "verified",
                    DiscoverExternalCandidate.imported_paper_id.is_not(None),
                )
            ).scalars()
            if row.imported_paper_id
        }
        items: list[RetrievalResultItem] = []
        seen_papers: set[str] = set()
        for item in response.items:
            if not item.paper_id or item.paper_id in excluded or item.paper_id in seen_papers:
                continue
            span = self._find_evidence_span(item)
            if item.evidence_level != "full_text" or span is None or span.relation != "supports":
                continue
            item.judgement = "supports"
            item.judgement_confidence = max(item.judgement_confidence, span.confidence)
            item.source_scope = "external" if item.paper_id in imported_ids else "workspace"
            items.append(item)
            seen_papers.add(item.paper_id)
        return response.model_copy(
            update={
                "purpose": "supporting_evidence",
                "items": items,
                "total": len(items),
                "filters_applied": {
                    **(response.filters_applied or {}),
                    "excluded_paper_ids": sorted(excluded),
                    "relation": "supports",
                    "requires_evidence_span": True,
                },
            }
        )

    def _external_fulltext(self, run: DiscoverRun, supporting: RetrievalResponse) -> RetrievalResponse:
        items = [item for item in supporting.items if item.source_scope == "external"]
        return supporting.model_copy(update={"purpose": "external_full_text", "items": items, "total": len(items)})

    def _evidence_gate(
        self,
        run: DiscoverRun,
        *,
        candidate: dict[str, Any] | None,
        supporting: RetrievalResponse,
        counter: RetrievalResponse,
    ) -> dict[str, Any]:
        """Evaluate only explicit, span-backed supporting evidence.

        Similar Work, Counter Evidence, metadata snapshots, and duplicate
        chunks are intentionally excluded from this set.
        """
        candidate_items = supporting.items
        if candidate is not None:
            candidate_items = self._supporting_for_candidate(candidate, supporting.items)
        valid: list[RetrievalResultItem] = []
        seen_papers: set[str] = set()
        for item in candidate_items:
            if item.paper_id in seen_papers or item.evidence_level != "full_text":
                continue
            span = self._find_evidence_span(item)
            if span is None or span.relation != "supports" or not span.artifact_id:
                continue
            if item.judgement != "supports":
                continue
            valid.append(item)
            seen_papers.add(item.paper_id or "")

        external_summary = (run.stage_summaries or {}).get("external_search") or {}
        external_executed = external_summary.get("status") in {"succeeded", "succeeded_empty"}
        counter_checked = counter.status in {"succeeded", "degraded"}
        reasons: list[str] = []
        if len(seen_papers) < 2:
            reasons.append("requires two independent full-text supporting papers")
        if not counter_checked:
            reasons.append(f"counter evidence status is {counter.status}")
        if not external_executed:
            reasons.append("external verification did not complete")
        coverage = self._evidence_coverage(candidate, valid)
        if coverage < 0.6:
            reasons.append("supporting evidence does not cover the opportunity's key problem and hypothesis")
        verified = not reasons
        return {
            "verified": verified,
            "independent_full_text_papers": len(seen_papers),
            "supporting_evidence_count": len(valid),
            "counter_checked": counter_checked,
            "counter_status": counter.status,
            "external_search_executed": external_executed,
            "external_search_status": external_summary.get("status", "not_run"),
            "evidence_coverage": coverage,
            "reason": "verified" if verified else "insufficient_full_text_evidence",
            "missing": reasons,
        }

    def _supporting_for_candidate(
        self, candidate: dict[str, Any], items: list[RetrievalResultItem]
    ) -> list[RetrievalResultItem]:
        fields = " ".join(
            str(candidate.get(key) or "")
            for key in ("problem_statement", "candidate_hypothesis", "why_existing_work_is_insufficient")
        )
        relevant = [item for item in items if self._text_relevant(fields, item.text)]
        return relevant or items

    @staticmethod
    def _text_relevant(candidate_text: str, evidence_text: str) -> bool:
        tokens = {token for token in re.findall(r"[a-zA-Z0-9]{4,}", candidate_text.lower())}
        evidence_tokens = {token for token in re.findall(r"[a-zA-Z0-9]{4,}", evidence_text.lower())}
        return len(tokens & evidence_tokens) >= 2

    def _evidence_coverage(
        self, candidate: dict[str, Any] | None, items: list[RetrievalResultItem]
    ) -> float:
        if not candidate or not items:
            return 0.0
        fields = [
            str(candidate.get("problem_statement") or ""),
            str(candidate.get("candidate_hypothesis") or ""),
            str(candidate.get("why_existing_work_is_insufficient") or ""),
        ]
        covered = sum(any(self._text_relevant(field, item.text) for item in items) for field in fields)
        papers = len({item.paper_id for item in items if item.paper_id})
        return round(min(1.0, (covered / len(fields)) * 0.7 + min(papers / 2, 1.0) * 0.3), 3)

    # ---------------------------------------------------------- synthesis
    def _synthesize_candidates(
        self,
        run: DiscoverRun,
        claim_text: str,
        supporting: RetrievalResponse,
        similar: RetrievalResponse,
        counter: RetrievalResponse,
        external_fulltext: RetrievalResponse,
        gate: dict[str, Any],
        maximum: int,
    ) -> list[dict[str, Any]]:
        evidence = {
            "supporting_evidence": [self._retrieval_payload(item) for item in supporting.items[:12]],
            "external_full_text": [self._retrieval_payload(item) for item in external_fulltext.items[:12]],
            "similar_work": [self._retrieval_payload(item) for item in similar.items[:12]],
            "counter_evidence": [self._retrieval_payload(item) for item in counter.items[:12]],
            "gate": gate,
            "constraints": (run.input_payload or {}).get("constraints"),
        }
        prompt = (
            "You are a conservative research-discovery agent. Return ONLY JSON with an "
            "opportunities array. Each item must include title, problem_statement, "
            "research_scope, why_existing_work_is_insufficient, candidate_research_question, "
            "candidate_hypothesis, candidate_validation_plan, open_risks, novelty_score, "
            "feasibility_score, significance_score, confidence. Do not invent papers. "
            "Keep supporting_evidence, similar_work, counter_evidence, and external_full_text "
            "as separate roles; similar_work is never supporting evidence. "
            "If evidence is incomplete, explicitly say verification is incomplete and keep "
            "scores conservative.\n\nCLAIM_OR_TOPIC:\n" + claim_text[:3000] +
            "\n\nEVIDENCE:\n" + json.dumps(evidence, ensure_ascii=False)
        )
        try:
            response = get_llm_gateway().chat_completion(
                [{"role": "system", "content": "You produce auditable research opportunity proposals."}, {"role": "user", "content": prompt}],
                temperature=0.1, max_tokens=2200,
            )
            parsed = self._parse_json(response.content)
            raw_items = parsed.get("opportunities") if isinstance(parsed, dict) else None
            if isinstance(raw_items, dict):
                raw_items = [raw_items]
            if isinstance(raw_items, list):
                normalized = [self._normalize_candidate(item, gate, provider="deepseek") for item in raw_items if isinstance(item, dict)]
                if normalized:
                    return normalized[:maximum]
        except Exception as exc:
            logger.warning("discover.synthesis_fallback", run_id=run.id, error=str(exc))
        return [self._fallback_candidate(claim_text, supporting, similar, counter, gate)]

    @staticmethod
    def _retrieval_payload(item: RetrievalResultItem) -> dict[str, Any]:
        return {"paper_id": item.paper_id, "title": item.paper_title, "text": item.text[:900], "score": item.score, "judgement": item.judgement, "evidence_level": item.evidence_level}

    @staticmethod
    def _normalize_candidate(value: dict[str, Any], gate: dict[str, Any], *, provider: str) -> dict[str, Any]:
        def score(key: str) -> float:
            try:
                return max(0.0, min(1.0, float(value.get(key, 0.35 if not gate["verified"] else 0.55))))
            except (TypeError, ValueError):
                return 0.35
        plan = value.get("candidate_validation_plan")
        if not isinstance(plan, dict):
            plan = {"steps": ["Select datasets and baselines", "Compare against the strongest similar-work setting", "Run an ablation for the suspected boundary condition"]}
        risks = value.get("open_risks")
        if not isinstance(risks, list):
            risks = ["External full-text verification is incomplete."]
        confidence = score("confidence") if gate["verified"] else min(score("confidence"), 0.49)
        return {
            "title": str(value.get("title") or "Investigate the boundary conditions of the topic")[:512],
            "problem_statement": str(value.get("problem_statement") or "The current evidence does not establish where the observed behavior generalizes."),
            "research_scope": str(value.get("research_scope") or "The scope should be narrowed to the datasets, models, and constraints available in this workspace."),
            "why_existing_work_is_insufficient": str(value.get("why_existing_work_is_insufficient") or "Existing work has not yet been compared under the same conditions."),
            "candidate_research_question": str(value.get("candidate_research_question") or "Under which conditions does the observed behavior remain reliable?"),
            "candidate_hypothesis": str(value.get("candidate_hypothesis") or "The behavior is strongest under the assumptions represented by the workspace evidence."),
            "candidate_validation_plan": plan,
            "open_risks": [str(item) for item in risks[:8]],
            "novelty_score": score("novelty_score"), "feasibility_score": score("feasibility_score"), "significance_score": score("significance_score"),
            "confidence": confidence, "evidence_coverage": 1.0 if gate["verified"] else min(0.49, gate["independent_full_text_papers"] / 4),
            "verification_status": "verified" if gate["verified"] else "verification_incomplete",
            "provider": provider,
        }

    @staticmethod
    def _fallback_candidate(claim_text: str, supporting: RetrievalResponse, similar: RetrievalResponse, counter: RetrievalResponse, gate: dict[str, Any]) -> dict[str, Any]:
        return DiscoverService._normalize_candidate({
            "title": "Investigate the boundary conditions of the claim",
            "problem_statement": "The claim is plausible but its boundary conditions are not yet established.",
            "why_existing_work_is_insufficient": f"The workspace returned {len(supporting.items)} supporting, {len(similar.items)} similar-work, and {len(counter.items)} counter-evidence passages, but the final evidence gate is incomplete.",
            "candidate_research_question": f"When does the following claim hold, and when does it fail? {claim_text[:500]}",
            "candidate_hypothesis": "The effect depends on a measurable data or model condition that can be isolated with an ablation.",
            "open_risks": ["External metadata is not a substitute for full-text evidence.", "The current retrieval set may be incomplete."],
        }, gate, provider="rule_based_fallback")

    def _persist_candidates(
        self,
        run: DiscoverRun,
        claim: KnowledgeItem | None,
        claim_text: str,
        supporting: RetrievalResponse,
        similar: RetrievalResponse,
        counter: RetrievalResponse,
        external_fulltext: RetrievalResponse,
        candidates: list[dict[str, Any]],
    ) -> tuple[list[ResearchOpportunity], list[dict[str, Any]]]:
        existing = list(self.db.execute(select(ResearchOpportunity).where(ResearchOpportunity.discover_run_id == run.id, ResearchOpportunity.is_deleted.is_(False))).scalars())
        if existing:
            gates = [
                (item.source_payload or {}).get("gate", {"verified": False, "reason": "idempotent_existing_result"})
                for item in existing
            ]
            return existing, gates
        created: list[ResearchOpportunity] = []
        final_gates: list[dict[str, Any]] = []
        external_rows = list(self.db.execute(select(DiscoverExternalCandidate).where(DiscoverExternalCandidate.discover_run_id == run.id)).scalars())
        for index, candidate in enumerate(candidates):
            candidate_support = self._supporting_for_candidate(candidate, supporting.items)
            candidate_supporting = supporting.model_copy(update={"items": candidate_support, "total": len(candidate_support)})
            gate = self._evidence_gate(run, candidate=candidate, supporting=candidate_supporting, counter=counter)
            candidate["evidence_coverage"] = gate["evidence_coverage"]
            candidate["verification_status"] = "verified" if gate["verified"] else "verification_incomplete"
            if not gate["verified"]:
                candidate["confidence"] = min(float(candidate.get("confidence", 0.0)), 0.49)
            final_gates.append(gate)
            opportunity = ResearchOpportunity(
                id=str(uuid4()), workspace_id=run.workspace_id, claim_item_id=claim.id if claim else None, discover_run_id=run.id,
                title=candidate["title"], summary=candidate["problem_statement"], rationale=candidate["why_existing_work_is_insufficient"],
                suggested_directions=list((candidate.get("candidate_validation_plan") or {}).get("steps", []))[:8], confidence=candidate["confidence"],
                status="candidate" if gate["verified"] else "needs_more_evidence",
                source_payload={"claim_text": claim_text, "gate": gate, "candidate_index": index, "synthesis_provider": candidate["provider"], "supporting_evidence": candidate_supporting.model_dump(mode="json"), "external_full_text": external_fulltext.model_dump(mode="json"), "similar_work": similar.model_dump(mode="json"), "counter_evidence": counter.model_dump(mode="json")},
                is_deleted=False,
            )
            self.db.add(opportunity)
            self.db.flush()
            version = OpportunityVersion(
                id=str(uuid4()), opportunity_id=opportunity.id, version_number=1, title=candidate["title"], problem_statement=candidate["problem_statement"], research_scope=candidate["research_scope"], why_existing_work_is_insufficient=candidate["why_existing_work_is_insufficient"], candidate_research_question=candidate["candidate_research_question"], candidate_hypothesis=candidate["candidate_hypothesis"], candidate_validation_plan=candidate["candidate_validation_plan"], open_risks=candidate["open_risks"], novelty_score=candidate["novelty_score"], feasibility_score=candidate["feasibility_score"], significance_score=candidate["significance_score"], confidence=candidate["confidence"], evidence_coverage=candidate["evidence_coverage"], verification_status=candidate["verification_status"], synthesis_metadata={"provider": candidate["provider"], "prompt_version": run.prompt_version, "retrieval_snapshot_version": run.retrieval_snapshot_version}, created_by="agent",
            )
            self.db.add(version)
            self.db.flush()
            opportunity.current_version_id = version.id
            opportunity.status = "candidate" if gate["verified"] else "needs_more_evidence"
            self._persist_evidence(version.id, candidate_supporting, similar, counter, external_rows)
            created.append(opportunity)
            self.timeline.record(workspace_id=run.workspace_id, event_type="opportunity.generated", subject_type="opportunity", subject_id=opportunity.id, actor="agent", payload={"run_id": run.id, "version_id": version.id, "verification_status": version.verification_status})
        self.db.commit()
        return created, final_gates

    def _persist_evidence(self, version_id: str, supporting: RetrievalResponse, similar: RetrievalResponse, counter: RetrievalResponse, external_rows: list[DiscoverExternalCandidate]) -> None:
        for rank, item in enumerate(supporting.items, start=1):
            span = self._find_evidence_span(item)
            self.db.add(OpportunityEvidence(id=str(uuid4()), opportunity_version_id=version_id, relation="supports", source_scope=item.source_scope, evidence_level=item.evidence_level, paper_id=item.paper_id, evidence_span_id=span.id if span else None, artifact_id=span.artifact_id if span else item.artifact_id, chunk_id=item.chunk_id, rank=rank, score=item.score, judgement="supports", judgement_confidence=item.judgement_confidence, display_excerpt=item.text[:2000], snapshot_payload=item.model_dump(mode="json")))
        for rank, item in enumerate(similar.items, start=1):
            span = self._find_evidence_span(item)
            self.db.add(OpportunityEvidence(id=str(uuid4()), opportunity_version_id=version_id, relation="similar", source_scope="workspace", evidence_level=item.evidence_level, paper_id=item.paper_id, evidence_span_id=span.id if span else None, artifact_id=span.artifact_id if span else item.artifact_id, chunk_id=item.chunk_id, rank=rank, score=item.score, display_excerpt=item.text[:2000], snapshot_payload=item.model_dump(mode="json")))
        for rank, item in enumerate(counter.items, start=1):
            relation = item.judgement if item.judgement in {"contradicts", "qualifies", "supports", "overlaps"} else "unknown"
            span = self._find_evidence_span(item)
            self.db.add(OpportunityEvidence(id=str(uuid4()), opportunity_version_id=version_id, relation=relation, source_scope="workspace", evidence_level=item.evidence_level, paper_id=item.paper_id, evidence_span_id=span.id if span else None, artifact_id=span.artifact_id if span else item.artifact_id, chunk_id=item.chunk_id, rank=rank, score=item.score, judgement=item.judgement, judgement_confidence=item.judgement_confidence, display_excerpt=item.text[:2000], snapshot_payload=item.model_dump(mode="json")))
        for row in external_rows[:12]:
            self.db.add(OpportunityEvidence(id=str(uuid4()), opportunity_version_id=version_id, relation=row.role, source_scope="external", evidence_level=row.evidence_level, external_candidate_id=row.id, paper_id=row.imported_paper_id, rank=row.rank, score=0.0, display_excerpt=(row.abstract or row.title)[:2000], snapshot_payload=row.snapshot_payload))

    def _find_evidence_span(self, item: RetrievalResultItem) -> EvidenceSpan | None:
        if not item.paper_id or not item.text:
            return None
        exact = self.db.execute(
            select(EvidenceSpan)
            .where(
                EvidenceSpan.paper_id == item.paper_id,
                EvidenceSpan.relation == "supports",
                EvidenceSpan.text.contains(item.text[:80]),
            )
            .order_by(EvidenceSpan.confidence.desc())
            .limit(1)
        ).scalars().first()
        if exact is not None:
            return exact
        spans = list(
            self.db.execute(
                select(EvidenceSpan)
                .where(EvidenceSpan.paper_id == item.paper_id, EvidenceSpan.relation == "supports")
                .order_by(EvidenceSpan.confidence.desc())
            ).scalars()
        )
        item_tokens = {token for token in re.findall(r"[a-zA-Z0-9]{4,}", item.text.lower())}
        return next(
            (
                span for span in spans
                if span.text and len(item_tokens & {token for token in re.findall(r"[a-zA-Z0-9]{4,}", span.text.lower())}) >= 2
            ),
            None,
        )

    def _find_span(self, item: RetrievalResultItem) -> str | None:
        span = self._find_evidence_span(item)
        return span.id if span else None

    # --------------------------------------------------------- opportunity
    def list_opportunities(self, workspace_id: str, *, status_filter: str | None, run_id: str | None, limit: int, offset: int) -> tuple[list[ResearchOpportunity], int]:
        base = select(ResearchOpportunity).where(ResearchOpportunity.workspace_id == workspace_id, ResearchOpportunity.is_deleted.is_(False))
        if status_filter: base = base.where(ResearchOpportunity.status == status_filter)
        if run_id: base = base.where(ResearchOpportunity.discover_run_id == run_id)
        items = list(self.db.execute(base.order_by(ResearchOpportunity.created_at.desc()).limit(limit).offset(offset)).scalars())
        total = int(self.db.execute(select(func.count()).select_from(base.subquery())).scalar() or 0)
        return items, total

    def get_opportunity(self, workspace_id: str, opportunity_id: str) -> ResearchOpportunity:
        item = self.db.get(ResearchOpportunity, opportunity_id)
        if item is None or item.is_deleted or item.workspace_id != workspace_id:
            raise OpportunityNotFoundError(opportunity_id)
        return item

    def opportunity_detail(self, workspace_id: str, opportunity_id: str) -> dict[str, Any]:
        item = self.get_opportunity(workspace_id, opportunity_id)
        versions = list(self.db.execute(select(OpportunityVersion).where(OpportunityVersion.opportunity_id == item.id).order_by(OpportunityVersion.version_number.desc())).scalars())
        current = next((version for version in versions if version.id == item.current_version_id), versions[0] if versions else None)
        evidence = list(self.db.execute(select(OpportunityEvidence).where(OpportunityEvidence.opportunity_version_id == current.id).order_by(OpportunityEvidence.rank)) .scalars()) if current else []
        decisions = list(self.db.execute(select(HumanDecision).where(HumanDecision.opportunity_id == item.id).order_by(HumanDecision.created_at.desc())).scalars())
        plan = self.db.execute(select(ResearchPlan).where(ResearchPlan.opportunity_id == item.id).order_by(ResearchPlan.created_at.desc())).scalars().first()
        return {"opportunity": item, "current_version": current, "versions": versions, "evidence": evidence, "decisions": decisions, "plan": plan}

    def opportunity_evidence_context(self, workspace_id: str, evidence_id: str) -> dict[str, Any]:
        evidence = self.db.get(OpportunityEvidence, evidence_id)
        if evidence is None:
            raise OpportunityNotFoundError(evidence_id)
        version = self.db.get(OpportunityVersion, evidence.opportunity_version_id)
        opportunity = self.db.get(ResearchOpportunity, version.opportunity_id) if version else None
        if opportunity is None or opportunity.workspace_id != workspace_id or opportunity.is_deleted:
            raise OpportunityNotFoundError(evidence_id)
        result: dict[str, Any] = {
            "evidence": evidence,
            "available": False,
            "paper_id": evidence.paper_id,
            "artifact_id": evidence.artifact_id,
            "artifact_kind": None,
            "filename": None,
            "content": None,
            "start_char": None,
            "end_char": None,
            "message": "This metadata-only evidence has no local full-text anchor.",
        }
        if not evidence.evidence_span_id:
            return result
        span = self.db.get(EvidenceSpan, evidence.evidence_span_id)
        if span is None or not span.artifact_id:
            return result
        artifact = self.db.get(Artifact, span.artifact_id)
        if artifact is None or artifact.is_deleted:
            result["message"] = "The source artifact is no longer available."
            return result
        path = ArtifactService(self.db).resolve_abs_path(artifact)
        if not path.exists():
            result["message"] = "The source artifact file is missing on disk."
            return result
        result.update(
            {
                "available": True,
                "artifact_id": artifact.id,
                "artifact_kind": artifact.kind,
                "filename": artifact.original_filename,
                "content": path.read_text(encoding="utf-8"),
                "start_char": span.start_char,
                "end_char": span.end_char,
                "message": None,
            }
        )
        return result

    def versions(self, workspace_id: str, opportunity_id: str) -> list[OpportunityVersion]:
        item = self.get_opportunity(workspace_id, opportunity_id)
        return list(self.db.execute(select(OpportunityVersion).where(OpportunityVersion.opportunity_id == item.id).order_by(OpportunityVersion.version_number.desc())).scalars())

    def confirm(self, workspace_id: str, opportunity_id: str, version_id: str | None, note: str | None) -> ResearchOpportunity:
        item = self.get_opportunity(workspace_id, opportunity_id)
        version = self._current_version(item, version_id)
        self._require_confirmable(version)
        action = "confirm"
        item.status = "confirmed"
        self._decision(item, version, version, action, note, None)
        self.db.commit()
        self.timeline.record(workspace_id=workspace_id, event_type="opportunity.confirmed", subject_type="opportunity", subject_id=item.id, actor="user", payload={"version_id": version.id, "note": note})
        return item

    def edit_confirm(self, workspace_id: str, opportunity_id: str, base_version_id: str, changes: dict[str, Any], note: str | None) -> ResearchOpportunity:
        item = self.get_opportunity(workspace_id, opportunity_id)
        base = self._current_version(item, base_version_id)
        if item.current_version_id != base_version_id:
            raise OpportunityVersionConflict("Opportunity has changed; refresh before editing")
        self._require_confirmable(base)
        data = {key: getattr(base, key) for key in ("title", "problem_statement", "research_scope", "why_existing_work_is_insufficient", "candidate_research_question", "candidate_hypothesis", "candidate_validation_plan", "open_risks", "novelty_score", "feasibility_score", "significance_score", "confidence", "evidence_coverage", "verification_status", "synthesis_metadata")}
        for key, value in changes.items():
            if key in data: data[key] = value
        number = int(self.db.execute(select(func.max(OpportunityVersion.version_number)).where(OpportunityVersion.opportunity_id == item.id)).scalar() or 0) + 1
        new_version = OpportunityVersion(id=str(uuid4()), opportunity_id=item.id, version_number=number, created_by="user", **data)
        self.db.add(new_version); self.db.flush(); item.current_version_id = new_version.id; item.status = "edited_confirmed"
        old_evidence = list(self.db.execute(select(OpportunityEvidence).where(OpportunityEvidence.opportunity_version_id == base.id)).scalars())
        for evidence in old_evidence:
            self.db.add(OpportunityEvidence(id=str(uuid4()), opportunity_version_id=new_version.id, relation=evidence.relation, source_scope=evidence.source_scope, evidence_level=evidence.evidence_level, paper_id=evidence.paper_id, external_candidate_id=evidence.external_candidate_id, evidence_span_id=evidence.evidence_span_id, artifact_id=evidence.artifact_id, chunk_id=evidence.chunk_id, rank=evidence.rank, score=evidence.score, judgement=evidence.judgement, judgement_confidence=evidence.judgement_confidence, display_excerpt=evidence.display_excerpt, snapshot_payload=evidence.snapshot_payload))
        self._decision(item, base, new_version, "edit_confirm", note, None)
        self.db.commit()
        self.timeline.record(workspace_id=workspace_id, event_type="opportunity.edited_confirmed", subject_type="opportunity", subject_id=item.id, actor="user", payload={"from_version_id": base.id, "to_version_id": new_version.id})
        return item

    def reject(self, workspace_id: str, opportunity_id: str, note: str | None) -> ResearchOpportunity:
        return self._simple_decision(workspace_id, opportunity_id, "rejected", "reject", note, None)

    def defer(self, workspace_id: str, opportunity_id: str, note: str | None, condition: str | None) -> ResearchOpportunity:
        return self._simple_decision(workspace_id, opportunity_id, "deferred", "defer", note, condition)

    def convert_to_plan(self, workspace_id: str, opportunity_id: str) -> ResearchPlan:
        item = self.get_opportunity(workspace_id, opportunity_id)
        if item.status not in {"confirmed", "edited_confirmed"}:
            raise DiscoverGateError("plan_requires_confirmed_opportunity", "Only a confirmed opportunity can become a research plan")
        version = self._current_version(item, None)
        existing = self.db.execute(select(ResearchPlan).where(ResearchPlan.opportunity_id == item.id, ResearchPlan.opportunity_version_id == version.id)).scalars().first()
        if existing: return existing
        plan_data = version.candidate_validation_plan or {}
        plan = ResearchPlan(id=str(uuid4()), workspace_id=workspace_id, opportunity_id=item.id, opportunity_version_id=version.id, status="draft", research_question=version.candidate_research_question, hypothesis=version.candidate_hypothesis, scope_and_assumptions=version.research_scope, datasets=list(plan_data.get("datasets", [])), baselines=list(plan_data.get("baselines", [])), metrics=list(plan_data.get("metrics", [])), validation_steps=list(plan_data.get("steps", [])), expected_supporting_result=str(plan_data.get("expected_supporting_result", "")), falsification_criteria=str(plan_data.get("falsification_criteria", "")), risks=list(version.open_risks), resource_constraints=str((self.get_run(workspace_id, item.discover_run_id).input_payload or {}).get("constraints", "")) if item.discover_run_id else "")
        self.db.add(plan); self.db.commit(); self.db.refresh(plan)
        self.timeline.record(workspace_id=workspace_id, event_type="plan.generated", subject_type="research_plan", subject_id=plan.id, actor="user", payload={"opportunity_id": item.id, "version_id": version.id})
        return plan

    def _simple_decision(self, workspace_id: str, opportunity_id: str, status: str, action: str, note: str | None, condition: str | None) -> ResearchOpportunity:
        item = self.get_opportunity(workspace_id, opportunity_id); version = self._current_version(item, None)
        if item.status in {"confirmed", "edited_confirmed"} and status in {"rejected", "deferred"}:
            raise InvalidOpportunityTransition("A confirmed opportunity cannot be rejected or deferred")
        item.status = status; self._decision(item, version, version, action, note, condition); self.db.commit()
        event = {"reject": "opportunity.rejected", "defer": "opportunity.deferred"}[action]
        self.timeline.record(workspace_id=workspace_id, event_type=event, subject_type="opportunity", subject_id=item.id, actor="user", payload={"version_id": version.id, "note": note, "defer_condition": condition})
        return item

    def _decision(self, item: ResearchOpportunity, from_version: OpportunityVersion, to_version: OpportunityVersion, action: str, note: str | None, condition: str | None) -> None:
        self.db.add(HumanDecision(id=str(uuid4()), opportunity_id=item.id, from_version_id=from_version.id, to_version_id=to_version.id, action=action, reason=note, defer_condition=condition, actor="user"))

    def _current_version(self, item: ResearchOpportunity, version_id: str | None) -> OpportunityVersion:
        version = self.db.get(OpportunityVersion, version_id or item.current_version_id) if (version_id or item.current_version_id) else None
        if version is None or version.opportunity_id != item.id: raise OpportunityVersionConflict("Requested version is not part of this opportunity")
        return version

    def _require_confirmable(self, version: OpportunityVersion) -> None:
        evidence_rows = list(self.db.execute(
            select(OpportunityEvidence).where(
                OpportunityEvidence.opportunity_version_id == version.id,
                OpportunityEvidence.relation == "supports",
                OpportunityEvidence.judgement == "supports",
                OpportunityEvidence.evidence_level == "full_text",
            )
        ).scalars())
        independent_papers = {
            evidence.paper_id
            for evidence in evidence_rows
            if evidence.paper_id and evidence.evidence_span_id and evidence.artifact_id
        }
        if (
            version.verification_status != "verified"
            or version.evidence_coverage < 0.6
            or len(independent_papers) < 2
        ):
            raise DiscoverGateError("insufficient_full_text_evidence", "At least two independent full-text evidence papers are required before confirmation")

    # ------------------------------------------------ legacy sync API
    def discover(self, workspace_id: str, request: Any) -> tuple[ResearchOpportunity, str, RetrievalResponse, RetrievalResponse]:
        """Compatibility path for the existing Claim drawer.

        It keeps the old response shape while new UI clients use async runs.
        """
        claim = self._resolve_claim(workspace_id, request.claim_item_id)
        claim_text = self._claim_text(claim) if claim else (request.claim_text or "").strip()
        if not claim_text: raise DiscoverInputError("claim text is empty")
        similar = find_similar_work(workspace_id, request.paper_id or (claim.paper_id if claim else ""), request.top_k, use_reranker=request.use_reranker) if request.paper_id or (claim and claim.paper_id) else self._empty_response(workspace_id, claim_text, "similar_work")
        counter = find_counter_evidence(workspace_id, claim_text, request.top_k, use_reranker=request.use_reranker, use_judge=request.use_judge, exclude_paper_ids={claim.paper_id} if claim and claim.paper_id else set())
        synthesis = self._fallback_candidate(claim_text, self._empty_response(workspace_id, claim_text, "supporting_evidence"), similar, counter, {"verified": False, "independent_full_text_papers": 0})
        opportunity = ResearchOpportunity(id=str(uuid4()), workspace_id=workspace_id, claim_item_id=claim.id if claim else None, title=synthesis["title"], summary=synthesis["problem_statement"], rationale=synthesis["why_existing_work_is_insufficient"], suggested_directions=list(synthesis["candidate_validation_plan"].get("steps", [])), confidence=synthesis["confidence"], status="needs_more_evidence", source_payload={"claim_text": claim_text, "similar_work": similar.model_dump(mode="json"), "counter_evidence": counter.model_dump(mode="json"), "synthesis_provider": synthesis["provider"]}, is_deleted=False)
        self.db.add(opportunity); self.db.commit(); self.db.refresh(opportunity)
        return opportunity, claim_text, similar, counter

    # -------------------------------------------------------------- helpers
    def _resolve_claim(self, workspace_id: str, claim_item_id: str | None) -> KnowledgeItem | None:
        if not claim_item_id: return None
        claim = self.db.get(KnowledgeItem, claim_item_id)
        if claim is None or claim.is_deleted or claim.workspace_id != workspace_id or claim.type != "claim":
            raise DiscoverInputError("claim_item_id must reference a claim in this workspace")
        return claim

    def _validate_papers(self, workspace_id: str, paper_ids: list[str]) -> None:
        if not paper_ids: return
        count = int(self.db.execute(select(func.count()).select_from(Paper).where(Paper.workspace_id == workspace_id, Paper.id.in_(paper_ids), Paper.is_deleted.is_(False))).scalar() or 0)
        if count != len(set(paper_ids)): raise DiscoverInputError("all selected papers must belong to this workspace")

    @staticmethod
    def _claim_text(item: KnowledgeItem | None) -> str:
        if item is None: return ""
        statement = (item.content or {}).get("statement")
        return statement.strip() if isinstance(statement, str) and statement.strip() else item.canonical_name.strip()

    @staticmethod
    def _empty_response(workspace_id: str, query: str, purpose: str) -> RetrievalResponse:
        return RetrievalResponse(request_id=str(uuid4()), workspace_id=workspace_id, query=query, purpose=purpose, status="succeeded", items=[], total=0)

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any] | None:
        match = re.search(r"\{[\s\S]*\}", content.strip())
        if not match: return None
        try: value = json.loads(match.group(0))
        except json.JSONDecodeError: return None
        return value if isinstance(value, dict) else None


def resume_discover_runs_for_paper(db: Session, paper_id: str, workspace_id: str) -> None:
    """Resume waiting Discover runs once an imported paper is fully ready."""
    service = DiscoverService(db)
    candidate_rows = list(
        db.execute(
            select(DiscoverExternalCandidate).where(
                DiscoverExternalCandidate.imported_paper_id == paper_id,
                DiscoverExternalCandidate.verification_status.in_([
                    "selected", "imported_pending_parse", "verification_failed", "verified"
                ]),
            )
        ).scalars()
    )
    run_ids = {row.discover_run_id for row in candidate_rows}
    for run_id in run_ids:
        run = db.get(DiscoverRun, run_id)
        if run is None or run.workspace_id != workspace_id or run.status != "waiting_for_fulltext":
            continue
        state = service._external_candidate_state(run)
        if state["pending"] or state["failed"] or not state["verified"]:
            if state["failed"] and not state["pending"]:
                service._wait_for_fulltext(run, state)
            continue
        run.status = "queued"
        run.stage = "fulltext_verification"
        run.progress = max(run.progress, 0.70)
        run.verification_status = "in_progress"
        run.stage_summaries = {
            **(run.stage_summaries or {}),
            "fulltext_verification": {
                "status": "succeeded",
                "verified": state["verified"],
                "resumed": True,
            },
        }
        try:
            if run.task_id:
                TaskService(db).resume_from_user(
                    run.task_id,
                    decision={"resumed_after_paper_id": paper_id},
                )
            db.commit()
            from app.workers.tasks.run_discover import spawn_discover_task

            celery_id = spawn_discover_task(run.id)
            if run.task_id:
                task = TaskService(db).get(run.task_id)
                task.celery_task_id = celery_id
            db.commit()
            service.timeline.record(
                workspace_id=run.workspace_id,
                event_type="discover.run_resumed",
                subject_type="discover_run",
                subject_id=run.id,
                actor="system",
                payload={"run_id": run.id, "paper_id": paper_id},
            )
        except Exception as exc:
            db.rollback()
            run = db.get(DiscoverRun, run_id)
            if run is not None:
                run.status = "waiting_for_fulltext"
                run.verification_status = "failed"
                run.stage_summaries = {
                    **(run.stage_summaries or {}),
                    "fulltext_verification": {
                        "status": "failed",
                        "retryable": True,
                        "error": str(exc)[:500],
                    },
                }
                db.commit()
            logger.warning(
                "discover.resume_failed",
                run_id=run_id,
                paper_id=paper_id,
                error=str(exc),
            )
