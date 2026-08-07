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

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.artifact.models import Artifact
from app.domains.artifact.service import ArtifactService
from app.domains.discover.adapters import (
    ExternalSearchAdapter,
    LLMGatewayAdapter,
    RetrievalAdapter,
    assert_protocol,
)
from app.domains.discover.models import (
    DiscoverExternalCandidate,
    DiscoverRun,
    HumanDecision,
    OpportunityEvidence,
    OpportunityVersion,
    ResearchOpportunity,
    ResearchPlan,
)
from app.domains.discover.opportunity_workflow import OpportunityWorkflow
from app.domains.discover.ports import ExternalSearchPort, LLMGatewayPort, RetrievalPort
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
from app.domains.task.models import Task
from app.domains.task.schemas import TaskCreate
from app.domains.task.service import TaskService
from app.domains.timeline.service import TimelineService
from app.gateway.semantic_scholar import SemanticScholarClient, SemanticScholarError

logger = get_logger(__name__)

S2_FIELDS = "paperId,externalIds,title,abstract,year,authors,openAccessPdf,url,publicationDate"
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "cancelled"}

# LLM prompt for external candidate role judgement (Stage 3).
EXTERNAL_ROLE_SYSTEM_PROMPT = """\
You classify whether external research papers serve as counter-evidence for a \
research question.

Categories:
- similar: same research area, closely related approach
- overlap: partially overlapping topic but different focus
- qualifies: adds caveats or limitations that constrain the research question
- contradicts: provides evidence against the research question
- unknown: cannot determine from the metadata alone

Rules:
- Be conservative: use "unknown" if ambiguous
- "contradicts" requires clear opposing evidence, not just a different focus
- Base your judgement on the title and abstract only
- A candidate that merely resembles the question is "similar"; only call it \
"qualifies" or "contradicts" when it explicitly challenges or constrains it

Output a JSON object, nothing else:
{"roles": [{"index": 0, "role": "similar|overlap|qualifies|contradicts|unknown", \
"confidence": 0.0-1.0}, ...]}"""
WAITING_RUN_STATUSES = {"waiting_for_user", "waiting_for_fulltext"}
PIPELINE_PENDING_STATUSES = {"queued", "running", "waiting_for_user"}

# LLM prompt for external-query axis decomposition (Stage 3). The research
# question alone (long prose) is a poor Semantic Scholar relevance query; the
# LLM decomposes it into concise, term-rich search queries that target
# foundational methods, overlapping work, counter-evidence, and evaluation /
# critique literature — with the workspace's extracted methods/limitations as
# context so queries cross research axes with the workspace's named methods.
EXTERNAL_QUERY_AXIS_SYSTEM_PROMPT = """\
You write effective search queries to find EXTERNAL papers that challenge, \
overlap with, or foundationally support a research question. The papers must \
be relevant to the question but are NOT required to be in the user's workspace.

Rules:
- Write CONCISE keyword-style queries (3-8 words), never full sentences
- Prefer SPECIFIC method names and established concept terms over generic \
topic phrases (e.g. "graph information bottleneck" or "invariant risk \
minimization", not just "interpretable GNN")
- Turn at least 2 of the workspace's abbreviated method names into concrete \
queries using their FULL names, so the search finds the method's paper plus \
its variants and critiques
- Cover distinct angles: foundational methods, overlapping prior work, \
counter-evidence / critiques, evaluation benchmarks, and the domain axis \
(e.g. distribution shift) when present
- Do not quote the workspace paper titles verbatim
- Never repeat the same idea in two queries

Also choose up to 4 workspace method names whose papers you want surfaced
PRECISELY (these are searched by exact title, so give the full descriptive
name — expand abbreviations). Prefer methods that are foundational or likely
to have counter-evidence / variants. Do not list the same method twice.

Examples of good queries:
- "graph information bottleneck"
- "invariant risk minimization out-of-distribution"
- "saliency maps sanity checks"
- "explanation robustness adversarial perturbations"
- "graph rationalization environment augmentation"

Output a JSON object, nothing else:
{"queries": ["...", "...", "..."], "exact_lookups": ["Method Full Name", "...", "..."]}"""

# Stage 3 external-query construction budget. A handful of focused queries
# covers more angles than the literal claim wording while keeping S2 API
# calls and the LLM role-judge batches bounded. The LLM-decomposed axis
# queries are the highest-value external-search keys, so they are prioritized
# over raw workspace signals and generic keywords.
EXTERNAL_QUERY_MAX_TOTAL = 12  # max external search queries per run
EXTERNAL_QUERY_AXIS_COUNT = 6  # LLM-generated axis queries to request
EXTERNAL_QUERY_MAX_EXACT_LOOKUPS = 4  # LLM-selected method names to look up by exact title
EXTERNAL_QUERY_SIGNAL_TYPES = ("method", "claim", "task", "limitation")
EXTERNAL_QUERY_MIN_CONFIDENCE = 0.3  # skip low-confidence extracted signals
EXTERNAL_QUERY_MAX_KEYWORDS = 2  # generic user keywords are lowest priority
# Architectural components are not named research contributions, so they are
# poor external-search keys; deprioritize them so real method names win.
EXTERNAL_METHOD_COMPONENT_TOKENS = {
    "pool", "module", "layer", "encoder", "decoder", "aggregation",
    "step", "fourier", "regularization", "block",
}

# Domain exception classes live in their own module so they can be
# imported by submodules (and tests) without dragging the whole service.
from app.domains.discover.exceptions import (  # noqa: E402
    DiscoverGateError,
    DiscoverInputError,
    DiscoverRunDeletionConflict,
    DiscoverRunCancelled,
    DiscoverRunNotFoundError,
    InvalidOpportunityTransition,
    OpportunityNotFoundError,
    OpportunityVersionConflict,
)


class DiscoverService(OpportunityWorkflow):
    def __init__(
        self,
        db: Session,
        *,
        retrieval: RetrievalPort | None = None,
        external_search: ExternalSearchPort | None = None,
        llm: LLMGatewayPort | None = None,
    ) -> None:
        self.db = db
        self.timeline = TimelineService(db)

        # Bind the cross-domain collaborators through Protocol ports (see
        # ``ports.py``). Tests can inject Protocol-compatible fakes to
        # exercise the orchestration without Milvus / DeepSeek / S2.
        self.retrieval: RetrievalPort = retrieval or RetrievalAdapter()
        self.external_search: ExternalSearchPort = external_search or ExternalSearchAdapter()
        self.llm: LLMGatewayPort = llm or LLMGatewayAdapter()

        # Cheap runtime sanity check — fails loudly if a custom binding is
        # missing a method the orchestrator calls.
        assert_protocol(self.retrieval, RetrievalPort)
        assert_protocol(self.external_search, ExternalSearchPort)
        assert_protocol(self.llm, LLMGatewayPort)

    # ---------------------------------------------------------------- runs
    def create_run(
        self,
        workspace_id: str,
        request: DiscoverRunCreateRequest,
        *,
        trigger_type: str = "topic",
        parent_run_id: str | None = None,
        actor: str = "user",
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
            actor=actor,
            payload={"run_id": run.id, "task_id": task.id, "trigger_type": trigger_type},
        )
        return run, task.id

    def list_runs(self, workspace_id: str, *, status_filter: str | None, limit: int, offset: int) -> tuple[list[DiscoverRun], int]:
        base = select(DiscoverRun).where(
            DiscoverRun.workspace_id == workspace_id,
            DiscoverRun.deleted_at.is_(None),
        )
        if status_filter:
            base = base.where(DiscoverRun.status == status_filter)
        items = list(self.db.execute(base.order_by(DiscoverRun.created_at.desc()).limit(limit).offset(offset)).scalars())
        total = int(self.db.execute(select(func.count()).select_from(base.subquery())).scalar() or 0)
        return items, total

    def get_run(self, workspace_id: str, run_id: str) -> DiscoverRun:
        run = self.db.get(DiscoverRun, run_id)
        if run is None or run.workspace_id != workspace_id or run.deleted_at is not None:
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

    def delete_run(self, workspace_id: str, run_id: str, *, actor: str = "user") -> None:
        """Hide a completed Discover Run without deleting its research data."""
        run = self.get_run(workspace_id, run_id)
        if run.status not in TERMINAL_RUN_STATUSES:
            raise DiscoverRunDeletionConflict(
                "Only completed, failed, or cancelled Discover runs can be deleted; cancel the active run first."
            )
        run.deleted_at = datetime.now(timezone.utc)
        run.deleted_by = actor
        self.db.commit()
        self.timeline.record(
            workspace_id=workspace_id,
            event_type="discover.run_deleted",
            subject_type="discover_run",
            subject_id=run.id,
            actor=actor,
            payload={"run_id": run.id, "preserved_outputs": True},
        )

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
        self._stage(
            run,
            "counter_evidence",
            0.42,
            {
                **self._counter_summary(counter),
                "status": counter.status,
            },
        )

        external_queries, exact_lookups = self._external_query_plan(run, claim_text)
        external = self._external_verify(run, external_queries, exact_lookups)
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
        self._checkpoint(run)
        finished_at = datetime.now(timezone.utc)
        verification_status = "complete" if any(gate["verified"] for gate in final_gates) else "incomplete"
        saved_summary = {"opportunities": len(created), "gates": final_gates}
        # A cancellation can arrive while synthesis or persistence is running.
        # Use a conditional UPDATE so a stale worker can never overwrite the
        # user's cancelled state with succeeded.
        result = self.db.execute(
            update(DiscoverRun)
            .where(DiscoverRun.id == run.id, DiscoverRun.status != "cancelled")
            .values(
                status="succeeded",
                stage="saved",
                progress=1.0,
                verification_status=verification_status,
                finished_at=finished_at,
                stage_summaries={
                    **(run.stage_summaries or {}),
                    "saved": saved_summary,
                },
            )
        )
        if result.rowcount != 1:
            self.db.rollback()
            cancelled = self.db.get(DiscoverRun, run.id)
            if cancelled is not None and cancelled.status == "cancelled":
                return self._cancelled_result(cancelled)
            raise DiscoverRunCancelled(run.id)
        self.db.commit()
        self.db.refresh(run)
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
            raise DiscoverRunCancelled(run.id)
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
            return self.retrieval.find_similar_work(run.workspace_id, paper_id, config.top_k, use_reranker=config.use_reranker, exclude_paper_ids={paper_id})
        return self.retrieval.semantic_search(run.workspace_id, text, config.top_k, use_reranker=config.use_reranker)

    def _workspace_counter(self, run: DiscoverRun, claim: KnowledgeItem | None, text: str, config: DiscoverConfig) -> RetrievalResponse:
        if not config.include_counter_evidence:
            return self._empty_response(run.workspace_id, text, "counter_evidence")
        excluded = {claim.paper_id} if claim and claim.paper_id else set()
        return self.retrieval.find_counter_evidence(run.workspace_id, text, config.top_k, use_reranker=config.use_reranker, use_judge=config.use_judge, exclude_paper_ids=excluded)

    def _external_verify(self, run: DiscoverRun, queries: list[str], exact_lookups: list[str] | None = None) -> int:
        """Search Semantic Scholar across several queries and merge candidates.

        ``queries[0]`` is the run's research question (claim/topic); the rest
        are extra angles built by ``_external_query_plan``. Results are
        deduped by ``external_paper_id`` and assigned fresh sequential ranks.
        Each candidate records the query that surfaced it, so the audit trail
        shows which workspace signal produced which candidate.

        ``exact_lookups`` are method names searched by exact title with
        title-verification — relevance search can be diluted by axis-suffix
        terms, so LLM-selected method names get a precise, verified pass whose
        hits are prepended to the merged candidates.
        """
        existing = int(self.db.execute(select(func.count()).select_from(DiscoverExternalCandidate).where(DiscoverExternalCandidate.discover_run_id == run.id)).scalar() or 0)
        if existing:
            rows = list(self.db.execute(select(DiscoverExternalCandidate).where(DiscoverExternalCandidate.discover_run_id == run.id)).scalars())
            self._external_candidate_state(run)
            return existing
        queries = [q.strip() for q in queries if q and q.strip()]
        if not queries:
            run.verification_status = "incomplete"
            self.db.commit()
            return 0
        primary = queries[0]
        config = DiscoverConfig.model_validate(run.config or {})
        top_k = config.top_k
        scope = DiscoverScope.model_validate(run.scope or {})
        year = None
        if scope.year_from is not None or scope.year_to is not None:
            year = f"{scope.year_from or ''}-{scope.year_to or ''}"
        per_query: list[list[tuple[str, dict[str, Any]]]] = []
        try:
            for position, query in enumerate(queries):
                limit = top_k if position == 0 else max(3, top_k // 2)
                raw = self.external_search.search(
                    query=query[:200],
                    fields=S2_FIELDS,
                    sort="relevance",
                    limit=limit,
                    year=year,
                )
                seen_in_query: set[str] = set()
                q_results: list[tuple[str, dict[str, Any]]] = []
                for item in raw.get("data") or []:
                    if not isinstance(item, dict) or not item.get("paperId") or not item.get("title"):
                        continue
                    pid = str(item["paperId"])
                    if pid not in seen_in_query:
                        seen_in_query.add(pid)
                        q_results.append((pid, item))
                per_query.append(q_results)
        except SemanticScholarError as exc:
            run.verification_status = "failed"
            run.stage_summaries = {**(run.stage_summaries or {}), "external_search": {"status": "failed", "error": str(exc), "retryable": exc.status_code in {429, 502, 504}, "executed": False, "queries": [q[:120] for q in queries]}}
            self.db.commit()
            logger.warning("discover.external_search_failed", run_id=run.id, error=str(exc))
            return 0

        # Exact-title lookups for LLM-selected method names (title-verified).
        # Best-effort: a failed lookup only skips that name, never fails the run.
        lookup_hits: list[tuple[str, dict[str, Any], str]] = []
        for name in exact_lookups or []:
            name = (name or "").strip()
            if not name:
                continue
            try:
                raw = self.external_search.search(
                    query=name[:200],
                    fields=S2_FIELDS,
                    sort="relevance",
                    limit=2,
                    year=year,
                )
            except SemanticScholarError:
                continue
            for item in raw.get("data") or []:
                if not isinstance(item, dict) or not item.get("paperId") or not item.get("title"):
                    continue
                if not self._title_verified(name, str(item["title"])):
                    continue
                lookup_hits.append((str(item["paperId"]), item, f"exact: {name[:120]}"))
                break  # one verified paper per lookup name

        # Round-robin interleave across queries so each query's top hits reach
        # the merged top-K — a primary-first merge would hide extra-query
        # discoveries below rank 10. Dedupe globally, attributing each paper
        # to the query that surfaced it earliest. Verified lookup hits are
        # prepended since they are the most certain matches.
        merged: list[tuple[str, dict[str, Any], str]] = []
        seen: set[str] = set()
        for pid, item, source_query in lookup_hits:
            if pid not in seen:
                seen.add(pid)
                merged.append((pid, item, source_query))
        round_index = 0
        while True:
            added_this_round = False
            for position, q_results in enumerate(per_query):
                if round_index < len(q_results):
                    pid, item = q_results[round_index]
                    if pid not in seen:
                        seen.add(pid)
                        merged.append((pid, item, queries[position][:200]))
                    added_this_round = True
            if not added_this_round:
                break
            round_index += 1

        rows: list[DiscoverExternalCandidate] = []
        for rank, (pid, item, source_query) in enumerate(merged, start=1):
            authors = [a.get("name", "") for a in item.get("authors") or [] if isinstance(a, dict) and a.get("name")]
            row = DiscoverExternalCandidate(
                id=str(uuid4()), discover_run_id=run.id, query=source_query, rank=rank,
                external_paper_id=pid, title=str(item["title"]), authors=authors,
                year=item.get("year") if isinstance(item.get("year"), int) else None,
                abstract=item.get("abstract") if isinstance(item.get("abstract"), str) else None,
                open_access_pdf=item.get("openAccessPdf") if isinstance(item.get("openAccessPdf"), dict) else None,
                role=self._external_role(primary, item), role_confidence=0.35,
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
                "queries": [q[:120] for q in queries],
            },
        }
        self.db.commit()
        # Refine candidate roles (similar/overlap/qualify/contradict/unknown)
        # with the LLM — the heuristic only gives similar/unknown. Failure
        # keeps the heuristic role; candidates remain auditable. Roles are
        # judged against the research question (the primary query).
        if rows:
            self._judge_external_roles(run, primary, rows)
        return len(rows)

    def _build_external_queries(self, run: DiscoverRun, primary: str) -> list[str]:
        """Backward-compatible list wrapper around ``_external_query_plan``."""
        return self._external_query_plan(run, primary)[0]

    def _external_query_plan(self, run: DiscoverRun, primary: str) -> tuple[list[str], list[str]]:
        """Build external-search queries and exact-lookup names.

        Returns ``(queries, exact_lookups)``. The primary query is the run's
        claim/topic (the research question itself). The LLM decomposes the
        research question into concise axis queries (foundational methods,
        counter-evidence, evaluation/critique, domain axis) and picks up to 4
        method names to look up by exact title. On LLM failure, or to fill the
        remaining budget, workspace-derived signals are used: method names,
        then limitations/claims/tasks, then generic user keywords last.
        Queries are deduped and capped by ``EXTERNAL_QUERY_MAX_TOTAL``.
        """
        queries: list[str] = []
        seen: set[str] = set()

        def add(text: str) -> bool:
            text = text.strip()
            if not text or text.lower() in seen:
                return False
            queries.append(text[:200])
            seen.add(text.lower())
            return True

        axis, lookups = self._axis_queries_from_llm(run, primary)
        add(primary)
        for axis_query in axis:
            add(axis_query)
            if len(queries) >= EXTERNAL_QUERY_MAX_TOTAL:
                return queries, lookups
        # Ground method names the LLM referenced: an embellished query like
        # "graph information bottleneck sufficiency necessity" surfaces
        # rationalization papers but often misses the method's own paper. The
        # exact method full-name matches S2 relevance far better, so each
        # method name mentioned in an axis query is also added as a clean
        # query (deduped).
        method_names = self._external_method_full_names(run.workspace_id)
        for axis_query in axis:
            axis_lower = axis_query.lower()
            for name in method_names:
                if len(name) >= 4 and name.lower() in axis_lower:
                    if add(name) and len(queries) >= EXTERNAL_QUERY_MAX_TOTAL:
                        return queries, lookups
        for item in self._external_query_signal_items(run.workspace_id, types=("method",)):
            add(self._external_query_text(item))
            if len(queries) >= EXTERNAL_QUERY_MAX_TOTAL:
                return queries, lookups
        for item in self._external_query_signal_items(run.workspace_id, types=("limitation", "claim", "task")):
            add(self._external_query_text(item))
            if len(queries) >= EXTERNAL_QUERY_MAX_TOTAL:
                return queries, lookups
        keyword_count = 0
        for kw in (run.input_payload or {}).get("keywords") or []:
            if not isinstance(kw, str) or keyword_count >= EXTERNAL_QUERY_MAX_KEYWORDS:
                continue
            if add(kw):
                keyword_count += 1
            if len(queries) >= EXTERNAL_QUERY_MAX_TOTAL:
                break
        return queries, lookups

    def _axis_queries_from_llm(self, run: DiscoverRun, primary: str) -> tuple[list[str], list[str]]:
        """Decompose the research question into external-search queries (LLM).

        Long prose is a poor relevance-search query. The LLM turns the
        research question into concise keyword-style queries that target the
        foundational / overlapping / counter / evaluation literature, using
        the workspace's extracted methods and limitations as context. It also
        picks up to 4 workspace method names to look up by exact title
        (``exact_lookups``). On LLM failure or a malformed response it returns
        ``([], [])`` so the caller falls back to workspace-signal queries.
        """
        signals = self._external_query_signal_texts(run.workspace_id)
        user_prompt = (
            f"RESEARCH QUESTION: {primary[:300]}\n\n"
            f"WORKSPACE SIGNALS (methods / limitations / claims to consider):\n"
            f"{signals if signals else '(none extracted)'}\n\n"
            f"Generate {EXTERNAL_QUERY_AXIS_COUNT} concise external-search queries "
            f"(3-8 words each). Include at least 2 queries derived from the "
            f"workspace method names, expanding abbreviations to their full names."
        )
        try:
            resp = self.llm.chat_completion(
                [
                    {"role": "system", "content": EXTERNAL_QUERY_AXIS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=800,
                disable_thinking=True,
            )
            parsed = self._parse_json(resp.content)
            if not isinstance(parsed, dict):
                logger.warning("discover.external_axis_query_bad_shape", raw_preview=(resp.content or "")[:200])
                return [], []
            queries: list[str] = []
            for q in parsed.get("queries") or []:
                if isinstance(q, str) and q.strip():
                    queries.append(q.strip())
            lookups: list[str] = []
            for name in parsed.get("exact_lookups") or []:
                if isinstance(name, str) and name.strip():
                    lookups.append(name.strip())
            return (
                queries[:EXTERNAL_QUERY_AXIS_COUNT],
                lookups[:EXTERNAL_QUERY_MAX_EXACT_LOOKUPS],
            )
        except Exception as exc:
            logger.warning("discover.external_axis_query_failed", error=str(exc))
            return [], []

    def _external_query_signal_texts(self, workspace_id: str, *, max_methods: int = 24, max_limitations: int = 6, max_claims: int = 6) -> str:
        """Compact workspace signals rendered for the axis-query LLM prompt."""
        lines: list[str] = []
        methods = self._external_query_signal_items(workspace_id, types=("method",))[:max_methods]
        if methods:
            lines.append("Methods: " + "; ".join(self._external_query_text(m) for m in methods))
        limitations = self._external_query_signal_items(workspace_id, types=("limitation",))[:max_limitations]
        if limitations:
            lines.append("Limitations: " + "; ".join(self._external_query_text(lim) for lim in limitations))
        claims = self._external_query_signal_items(workspace_id, types=("claim",))[:max_claims]
        if claims:
            lines.append("Claims: " + "; ".join(self._external_query_text(cl) for cl in claims))
        return "\n".join(lines)

    def _external_method_full_names(self, workspace_id: str, *, max_names: int = 40) -> list[str]:
        """Deduplicated method full-name queries used to ground LLM axis queries."""
        names: list[str] = []
        seen: set[str] = set()
        for item in self._external_query_signal_items(workspace_id, types=("method",)):
            name = self._external_query_text(item).strip()
            key = name.lower()
            if len(name) < 4 or key in seen:
                continue
            seen.add(key)
            names.append(name)
            if len(names) >= max_names:
                break
        return names

    def _external_query_signal_items(self, workspace_id: str, types: tuple[str, ...] | None = None) -> list[KnowledgeItem]:
        """Workspace items ordered by usefulness for external queries.

        Methods first (named entities → strongest external-search keys),
        deprioritizing architectural components (Pool/Module/Layer) and
        parenthesized sub-module aliases ("Self-Denoising (SD)") so real named
        methods (GIB, IRM, SubgraphX, GSAT…) surface; then limitations (caveats
        → counter-evidence), claims, tasks. Rejected and low-confidence items
        are skipped so a noisy extraction cannot pollute the external search.
        """
        types = types or EXTERNAL_QUERY_SIGNAL_TYPES
        items = list(
            self.db.execute(
                select(KnowledgeItem).where(
                    KnowledgeItem.workspace_id == workspace_id,
                    KnowledgeItem.is_deleted.is_(False),
                    KnowledgeItem.status != "rejected",
                    KnowledgeItem.type.in_(types),
                    KnowledgeItem.confidence >= EXTERNAL_QUERY_MIN_CONFIDENCE,
                )
            ).scalars()
        )
        type_rank = {"limitation": 0, "claim": 1, "task": 2}

        def is_component(item: KnowledgeItem) -> bool:
            words = {w.lower() for w in re.findall(r"[A-Za-z]+", item.canonical_name)}
            return bool(words & EXTERNAL_METHOD_COMPONENT_TOKENS)

        def is_parens_alias(item: KnowledgeItem) -> bool:
            return "(" in item.canonical_name or ")" in item.canonical_name

        def priority(item: KnowledgeItem) -> tuple[float, float]:
            if item.type == "method":
                if is_component(item):
                    return (3.0, -float(item.confidence or 0.0))
                if is_parens_alias(item):
                    return (2.0, -float(item.confidence or 0.0))
                return (0.0, -float(item.confidence or 0.0))
            return (type_rank.get(item.type, 9) + 10.0, -float(item.confidence or 0.0))

        items.sort(key=priority)
        return items

    def _external_query_text(self, item: KnowledgeItem) -> str:
        """Render a KnowledgeItem as an external-search query string.

        Methods render as their descriptive name: a multi-word canonical name
        is used as-is; an all-caps abbreviation is expanded from the leading
        noun phrase of its description (e.g. ``IRM`` → "Invariant Risk
        Minimization") when available. Limitations render as their short
        canonical name (caveats → counter-evidence); claims render as their
        statement.
        """
        content = item.content or {}
        if item.type == "claim":
            return self._claim_text(item)
        if item.type == "method":
            name = item.canonical_name.strip()
            if len(name.split()) >= 2 or not re.fullmatch(r"[A-Z]{2,5}", name):
                return name
            description = content.get("description")
            if isinstance(description, str) and description.strip():
                match = re.match(r"[A-Z][a-zA-Z0-9-]*(?:\s+[A-Z][a-zA-Z0-9-]*){1,3}", description.strip())
                full = match.group(0) if match else ""
                first = full.split()[0].lower() if full else ""
                if full and len(full.split()) >= 2 and full.lower() != name.lower() and first not in {"a", "an", "the"}:
                    return full
            return name
        # limitations and tasks: short canonical names carry the most signal;
        # long descriptions dilute S2 relevance matching.
        return item.canonical_name.strip()

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

    @staticmethod
    def _title_verified(name: str, title: str) -> bool:
        """Accept an exact-title lookup hit when the query words appear in the title."""
        query_words = set(re.findall(r"[a-z0-9]+", name.lower()))
        title_words = set(re.findall(r"[a-z0-9]+", title.lower()))
        if len(query_words) < 2:
            return False
        return query_words.issubset(title_words)

    def _judge_external_roles(
        self,
        run: DiscoverRun,
        query: str,
        candidates: list[DiscoverExternalCandidate],
    ) -> None:
        """LLM-refine external candidate roles.

        ``_external_role`` is a cheap word-overlap heuristic that only yields
        similar/unknown. Stage 3 requires discriminating similar / overlap /
        qualify / contradict / unknown so Discover can tell which external
        paper might *challenge* an opportunity, not just resemble it.

        This batch-judges candidates against the research question using the
        LLM gateway. On failure it silently keeps the heuristic role (the
        candidate rows already carry a role from ``_external_role``).
        """
        if not candidates:
            return
        # Reuse the injected LLM port; fall back to the heuristic result if
        # the LLM call throws (candidates already have a heuristic role).
        gateway = self.llm
        batch_size = 8
        role_map = {
            "similar": "similar",
            "overlaps": "overlap",
            "overlap": "overlap",
            "qualifies": "qualifies",
            "qualify": "qualifies",
            "contradicts": "contradicts",
            "contradict": "contradicts",
            "unknown": "unknown",
        }

        for start in range(0, len(candidates), batch_size):
            batch = candidates[start : start + batch_size]
            lines = [
                f"[{i}] {c.title or ''} — {(c.abstract or '')[:400]}"
                for i, c in enumerate(batch)
            ]
            user_prompt = (
                f"RESEARCH QUESTION: {query[:300]}\n\nCANDIDATES:\n" + "\n".join(lines)
            )
            try:
                resp = gateway.chat_completion(
                    [
                        {"role": "system", "content": EXTERNAL_ROLE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.0,
                    max_tokens=2000,
                    disable_thinking=True,
                )
                parsed = self._parse_json(resp.content)
                items = parsed.get("roles") if isinstance(parsed, dict) else None
                if not isinstance(items, list):
                    logger.warning("discover.external_role_bad_shape", raw_preview=(resp.content or "")[:200])
                    continue
                for hit in items:
                    if not isinstance(hit, dict):
                        continue
                    idx = hit.get("index")
                    if not isinstance(idx, int) or not (0 <= idx < len(batch)):
                        continue
                    role = str(hit.get("role", "unknown")).lower()
                    candidate = batch[idx]
                    candidate.role = role_map.get(role, "unknown")
                    try:
                        candidate.role_confidence = float(hit.get("confidence", 0.3))
                    except (TypeError, ValueError):
                        candidate.role_confidence = 0.3
            except Exception as exc:
                logger.warning("discover.external_role_judge_failed", error=str(exc))
                # Keep the heuristic role (already set on the rows) on failure.
        # Persist refined roles once, after all batches.
        self.db.commit()

    def _workspace_supporting(
        self,
        run: DiscoverRun,
        claim: KnowledgeItem | None,
        text: str,
        config: DiscoverConfig,
    ) -> RetrievalResponse:
        excluded = {claim.paper_id} if claim and claim.paper_id else set()
        response = self.retrieval.semantic_search(run.workspace_id, text, config.top_k * 3, use_reranker=config.use_reranker)
        return self._filter_supporting_response(run, response, excluded)

    def _candidate_supporting(
        self,
        run: DiscoverRun,
        claim: KnowledgeItem | None,
        candidate: dict[str, Any],
        config: DiscoverConfig,
    ) -> RetrievalResponse:
        """Retrieve evidence for the concrete synthesized opportunity.

        The initial topic retrieval is only a context builder. Final Gate
        evidence must be re-retrieved against the candidate's problem and
        hypothesis so broad topic matches cannot be promoted to support.
        """
        query = " ".join(
            str(candidate.get(key) or "")
            for key in (
                "problem_statement",
                "candidate_hypothesis",
                "why_existing_work_is_insufficient",
            )
        ).strip()
        excluded = {claim.paper_id} if claim and claim.paper_id else set()
        response = self.retrieval.semantic_search(
            run.workspace_id,
            query[:3000] or (run.input_topic or ""),
            config.top_k * 3,
            use_reranker=config.use_reranker,
        )
        return self._filter_supporting_response(run, response, excluded)

    def _filter_supporting_response(
        self,
        run: DiscoverRun,
        response: RetrievalResponse,
        excluded: set[str],
    ) -> RetrievalResponse:
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
            if (
                item.evidence_level != "full_text"
                or span is None
                or span.relation != "supports"
                or not self._has_valid_evidence_anchor(span, item.text)
            ):
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

    @staticmethod
    def _counter_summary(response: RetrievalResponse) -> dict[str, Any]:
        judgements = [item.judgement for item in response.items]
        found = [value for value in judgements if value in {"contradicts", "qualifies"}]
        if response.status == "failed":
            outcome = "retrieval_failed"
        elif response.status == "degraded":
            outcome = "judge_degraded_or_failed"
        elif found:
            outcome = "found"
        else:
            outcome = "searched_no_counter_evidence"
        return {
            "outcome": outcome,
            "found": len(found),
            "contradicts": judgements.count("contradicts"),
            "qualifies": judgements.count("qualifies"),
            "items": len(response.items),
        }

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
            if (
                span is None
                or span.relation != "supports"
                or not self._has_valid_evidence_anchor(span, item.text)
            ):
                continue
            if item.judgement != "supports":
                continue
            valid.append(item)
            seen_papers.add(item.paper_id or "")

        external_summary = (run.stage_summaries or {}).get("external_search") or {}
        external_executed = external_summary.get("status") in {"succeeded", "succeeded_empty"}
        supporting_checked = supporting.status == "succeeded"
        counter_checked = counter.status == "succeeded"
        reasons: list[str] = []
        if len(seen_papers) < 2:
            reasons.append("requires two independent full-text supporting papers")
        if not supporting_checked:
            reasons.append(f"supporting evidence retrieval status is {supporting.status}")
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
            "supporting_status": supporting.status,
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
        return [item for item in items if self._text_relevant(fields, item.text)]

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

    def _has_valid_evidence_anchor(self, span: EvidenceSpan, evidence_text: str | None = None) -> bool:
        if not span.artifact_id or span.start_char is None or span.end_char is None:
            return False
        if span.end_char <= span.start_char:
            return False
        artifact = self.db.get(Artifact, span.artifact_id)
        if artifact is None or artifact.is_deleted:
            return False
        if not evidence_text or not span.text:
            return True
        normalize = lambda value: " ".join(value.lower().split())
        span_text = normalize(span.text)
        item_text = normalize(evidence_text)
        if span_text in item_text or item_text in span_text:
            return True
        span_tokens = set(re.findall(r"[a-zA-Z0-9]{4,}", span_text))
        item_tokens = set(re.findall(r"[a-zA-Z0-9]{4,}", item_text))
        overlap = len(span_tokens & item_tokens)
        return overlap >= 3 and overlap / max(1, len(span_tokens)) >= 0.5

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
            response = self.llm.chat_completion(
                [{"role": "system", "content": "You produce auditable research opportunity proposals."}, {"role": "user", "content": prompt}],
                temperature=0.1, max_tokens=2200,
                disable_thinking=True,  # structured JSON — avoid CoT burning the budget
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
            # Re-run supporting retrieval for each concrete proposal. The
            # pre-synthesis topic retrieval remains context only.
            config = DiscoverConfig.model_validate(run.config or {})
            candidate_supporting = self._candidate_supporting(run, claim, candidate, config)
            gate = self._evidence_gate(run, candidate=candidate, supporting=candidate_supporting, counter=counter)
            candidate["evidence_coverage"] = gate["evidence_coverage"]
            candidate["verification_status"] = "verified" if gate["verified"] else "verification_incomplete"
            if not gate["verified"]:
                candidate["confidence"] = min(float(candidate.get("confidence", 0.0)), 0.49)
            final_gates.append(gate)
            candidate_external_fulltext = self._external_fulltext(run, candidate_supporting)
            opportunity = ResearchOpportunity(
                id=str(uuid4()), workspace_id=run.workspace_id, claim_item_id=claim.id if claim else None, discover_run_id=run.id,
                title=candidate["title"], summary=candidate["problem_statement"], rationale=candidate["why_existing_work_is_insufficient"],
                suggested_directions=list((candidate.get("candidate_validation_plan") or {}).get("steps", []))[:8], confidence=candidate["confidence"],
                status="candidate" if gate["verified"] else "needs_more_evidence",
                source_payload={"claim_text": claim_text, "gate": gate, "candidate_index": index, "synthesis_provider": candidate["provider"], "supporting_evidence": candidate_supporting.model_dump(mode="json"), "external_full_text": candidate_external_fulltext.model_dump(mode="json"), "similar_work": similar.model_dump(mode="json"), "counter_evidence": counter.model_dump(mode="json")},
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
