"""Opportunity workflow: listing, decisions (confirm/reject/defer/edit), and plan conversion.

This is one of the three sub-aggregates extracted from the original
``service.py``. The other two (``external_sourcing`` and the inline
orchestrator) still live next to it because their internal call structure
is too dense to split without growing the diff beyond useful.

Each method here used to live as a method on ``DiscoverService``; the
``_WorkflowHelper`` mixin pattern keeps the call sites in ``service.py``
working without rewiring every ``self.X`` access.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from app.domains.discover.exceptions import (
    DiscoverGateError,
    InvalidOpportunityTransition,
    OpportunityNotFoundError,
    OpportunityVersionConflict,
)
from app.domains.discover.models import (
    HumanDecision,
    OpportunityEvidence,
    OpportunityVersion,
    ResearchOpportunity,
    ResearchPlan,
)
from app.domains.knowledge.models import EvidenceSpan
from app.domains.artifact.service import ArtifactService
from app.domains.artifact.models import Artifact


class OpportunityWorkflow:
    """Mixin-style helpers for the Opportunity state machine.

    Mixed into ``DiscoverService``. Methods call ``self.db`` and
    ``self.timeline``; those are the only attributes they depend on from
    the outer service.
    """

    # ------------------------------------------------------- read paths
    def list_opportunities(
        self,
        workspace_id: str,
        *,
        status_filter: str | None,
        run_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ResearchOpportunity], int]:
        base = select(ResearchOpportunity).where(
            ResearchOpportunity.workspace_id == workspace_id,
            ResearchOpportunity.is_deleted.is_(False),
        )
        if status_filter:
            base = base.where(ResearchOpportunity.status == status_filter)
        if run_id:
            base = base.where(ResearchOpportunity.discover_run_id == run_id)
        items = list(
            self.db.execute(
                base.order_by(ResearchOpportunity.created_at.desc()).limit(limit).offset(offset)
            ).scalars()
        )
        total = int(
            self.db.execute(select(func.count()).select_from(base.subquery())).scalar() or 0
        )
        return items, total

    def get_opportunity(self, workspace_id: str, opportunity_id: str) -> ResearchOpportunity:
        item = self.db.get(ResearchOpportunity, opportunity_id)
        if item is None or item.is_deleted or item.workspace_id != workspace_id:
            raise OpportunityNotFoundError(opportunity_id)
        return item

    def opportunity_detail(self, workspace_id: str, opportunity_id: str) -> dict[str, Any]:
        item = self.get_opportunity(workspace_id, opportunity_id)
        versions = list(
            self.db.execute(
                select(OpportunityVersion)
                .where(OpportunityVersion.opportunity_id == item.id)
                .order_by(OpportunityVersion.version_number.desc())
            ).scalars()
        )
        current = next(
            (v for v in versions if v.id == item.current_version_id),
            versions[0] if versions else None,
        )
        evidence = (
            list(
                self.db.execute(
                    select(OpportunityEvidence)
                    .where(OpportunityEvidence.opportunity_version_id == current.id)
                    .order_by(OpportunityEvidence.rank)
                ).scalars()
            )
            if current
            else []
        )
        decisions = list(
            self.db.execute(
                select(HumanDecision)
                .where(HumanDecision.opportunity_id == item.id)
                .order_by(HumanDecision.created_at.desc())
            ).scalars()
        )
        plan = (
            self.db.execute(
                select(ResearchPlan)
                .where(ResearchPlan.opportunity_id == item.id)
                .order_by(ResearchPlan.created_at.desc())
            )
            .scalars()
            .first()
        )
        return {
            "opportunity": item,
            "current_version": current,
            "versions": versions,
            "evidence": evidence,
            "decisions": decisions,
            "plan": plan,
        }

    def versions(self, workspace_id: str, opportunity_id: str) -> list[OpportunityVersion]:
        item = self.get_opportunity(workspace_id, opportunity_id)
        return list(
            self.db.execute(
                select(OpportunityVersion)
                .where(OpportunityVersion.opportunity_id == item.id)
                .order_by(OpportunityVersion.version_number.desc())
            ).scalars()
        )

    # ----------------------------------------------------- evidence view
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

    # ----------------------------------------------------- decision paths
    def confirm(
        self,
        workspace_id: str,
        opportunity_id: str,
        version_id: str | None,
        note: str | None,
        actor: str = "user",
    ) -> ResearchOpportunity:
        item = self.get_opportunity(workspace_id, opportunity_id)
        version = self._current_version(item, version_id)
        self._require_confirmable(version)
        item.status = "confirmed"
        self._decision(item, version, version, "confirm", note, None, actor=actor)
        self.db.commit()
        self.timeline.record(
            workspace_id=workspace_id,
            event_type="opportunity.confirmed",
            subject_type="opportunity",
            subject_id=item.id,
            actor=actor,
            payload={"version_id": version.id, "note": note},
        )
        return item

    def edit_confirm(
        self,
        workspace_id: str,
        opportunity_id: str,
        base_version_id: str,
        changes: dict[str, Any],
        note: str | None,
        actor: str = "user",
    ) -> ResearchOpportunity:
        item = self.get_opportunity(workspace_id, opportunity_id)
        base = self._current_version(item, base_version_id)
        if item.current_version_id != base_version_id:
            raise OpportunityVersionConflict("Opportunity has changed; refresh before editing")
        self._require_confirmable(base)
        data = {
            key: getattr(base, key)
            for key in (
                "title",
                "problem_statement",
                "research_scope",
                "why_existing_work_is_insufficient",
                "candidate_research_question",
                "candidate_hypothesis",
                "candidate_validation_plan",
                "open_risks",
                "novelty_score",
                "feasibility_score",
                "significance_score",
                "confidence",
                "evidence_coverage",
                "verification_status",
                "synthesis_metadata",
            )
        }
        for key, value in changes.items():
            if key in data:
                data[key] = value
        number = (
            int(
                self.db.execute(
                    select(func.max(OpportunityVersion.version_number)).where(
                        OpportunityVersion.opportunity_id == item.id
                    )
                ).scalar()
                or 0
            )
            + 1
        )
        new_version = OpportunityVersion(
            id=str(uuid4()),
            opportunity_id=item.id,
            version_number=number,
            created_by="user",
            **data,
        )
        self.db.add(new_version)
        self.db.flush()
        item.current_version_id = new_version.id
        item.status = "edited_confirmed"

        old_evidence = list(
            self.db.execute(
                select(OpportunityEvidence).where(OpportunityEvidence.opportunity_version_id == base.id)
            ).scalars()
        )
        for ev in old_evidence:
            self.db.add(
                OpportunityEvidence(
                    id=str(uuid4()),
                    opportunity_version_id=new_version.id,
                    relation=ev.relation,
                    source_scope=ev.source_scope,
                    evidence_level=ev.evidence_level,
                    paper_id=ev.paper_id,
                    external_candidate_id=ev.external_candidate_id,
                    evidence_span_id=ev.evidence_span_id,
                    artifact_id=ev.artifact_id,
                    chunk_id=ev.chunk_id,
                    rank=ev.rank,
                    score=ev.score,
                    judgement=ev.judgement,
                    judgement_confidence=ev.judgement_confidence,
                    display_excerpt=ev.display_excerpt,
                    snapshot_payload=ev.snapshot_payload,
                )
            )
        self._decision(item, base, new_version, "edit_confirm", note, None)
        self.db.commit()
        self.timeline.record(
            workspace_id=workspace_id,
            event_type="opportunity.edited_confirmed",
            subject_type="opportunity",
            subject_id=item.id,
            actor=actor,
            payload={"from_version_id": base.id, "to_version_id": new_version.id},
        )
        return item

    def reject(
        self,
        workspace_id: str,
        opportunity_id: str,
        note: str | None,
        actor: str = "user",
    ) -> ResearchOpportunity:
        return self._simple_decision(workspace_id, opportunity_id, "rejected", "reject", note, None, actor=actor)

    def defer(
        self,
        workspace_id: str,
        opportunity_id: str,
        note: str | None,
        condition: str | None,
        actor: str = "user",
    ) -> ResearchOpportunity:
        return self._simple_decision(workspace_id, opportunity_id, "deferred", "defer", note, condition, actor=actor)

    def convert_to_plan(
        self,
        workspace_id: str,
        opportunity_id: str,
        actor: str = "user",
    ) -> ResearchPlan:
        item = self.get_opportunity(workspace_id, opportunity_id)
        if item.status not in {"confirmed", "edited_confirmed"}:
            raise DiscoverGateError(
                "plan_requires_confirmed_opportunity",
                "Only a confirmed opportunity can become a research plan",
            )
        version = self._current_version(item, None)
        existing = self.db.execute(
            select(ResearchPlan).where(
                ResearchPlan.opportunity_id == item.id,
                ResearchPlan.opportunity_version_id == version.id,
            )
        ).scalars().first()
        if existing:
            return existing
        plan_data = version.candidate_validation_plan or {}
        run = self.get_run(workspace_id, item.discover_run_id) if item.discover_run_id else None
        constraints = (run.input_payload or {}).get("constraints", "") if run else ""
        plan = ResearchPlan(
            id=str(uuid4()),
            workspace_id=workspace_id,
            opportunity_id=item.id,
            opportunity_version_id=version.id,
            status="draft",
            research_question=version.candidate_research_question,
            hypothesis=version.candidate_hypothesis,
            scope_and_assumptions=version.research_scope,
            datasets=list(plan_data.get("datasets", [])),
            baselines=list(plan_data.get("baselines", [])),
            metrics=list(plan_data.get("metrics", [])),
            validation_steps=list(plan_data.get("steps", [])),
            expected_supporting_result=str(plan_data.get("expected_supporting_result", "")),
            falsification_criteria=str(plan_data.get("falsification_criteria", "")),
            risks=list(version.open_risks),
            resource_constraints=str(constraints),
        )
        self.db.add(plan)
        self.db.commit()
        self.db.refresh(plan)
        self.timeline.record(
            workspace_id=workspace_id,
            event_type="plan.generated",
            subject_type="research_plan",
            subject_id=plan.id,
            actor=actor,
            payload={"opportunity_id": item.id, "version_id": version.id},
        )
        return plan

    # ------------------------------------------------------- internal helpers
    def _simple_decision(
        self,
        workspace_id: str,
        opportunity_id: str,
        status: str,
        action: str,
        note: str | None,
        condition: str | None,
        actor: str = "user",
    ) -> ResearchOpportunity:
        item = self.get_opportunity(workspace_id, opportunity_id)
        version = self._current_version(item, None)
        if item.status in {"confirmed", "edited_confirmed"} and status in {"rejected", "deferred"}:
            raise InvalidOpportunityTransition(
                "A confirmed opportunity cannot be rejected or deferred"
            )
        item.status = status
        self._decision(item, version, version, action, note, condition, actor=actor)
        self.db.commit()
        event = {"reject": "opportunity.rejected", "defer": "opportunity.deferred"}[action]
        self.timeline.record(
            workspace_id=workspace_id,
            event_type=event,
            subject_type="opportunity",
            subject_id=item.id,
            actor=actor,
            payload={"version_id": version.id, "note": note, "defer_condition": condition},
        )
        return item

    def _decision(
        self,
        item: ResearchOpportunity,
        from_version: OpportunityVersion,
        to_version: OpportunityVersion,
        action: str,
        note: str | None,
        condition: str | None,
        actor: str = "user",
    ) -> None:
        self.db.add(
            HumanDecision(
                id=str(uuid4()),
                opportunity_id=item.id,
                from_version_id=from_version.id,
                to_version_id=to_version.id,
                action=action,
                reason=note,
                defer_condition=condition,
                actor=actor,
            )
        )

    def _current_version(self, item: ResearchOpportunity, version_id: str | None) -> OpportunityVersion:
        target_id = version_id or item.current_version_id
        version = self.db.get(OpportunityVersion, target_id) if target_id else None
        if version is None or version.opportunity_id != item.id:
            raise OpportunityVersionConflict("Requested version is not part of this opportunity")
        return version

    def _require_confirmable(self, version: OpportunityVersion) -> None:
        evidence_rows = list(
            self.db.execute(
                select(OpportunityEvidence).where(
                    OpportunityEvidence.opportunity_version_id == version.id,
                    OpportunityEvidence.relation == "supports",
                    OpportunityEvidence.judgement == "supports",
                    OpportunityEvidence.evidence_level == "full_text",
                )
            ).scalars()
        )
        independent_papers = {
            ev.paper_id
            for ev in evidence_rows
            if ev.paper_id and ev.evidence_span_id and ev.artifact_id
        }
        if (
            version.verification_status != "verified"
            or version.evidence_coverage < 0.6
            or len(independent_papers) < 2
        ):
            raise DiscoverGateError(
                "insufficient_full_text_evidence",
                "At least two independent full-text evidence papers are required before confirmation",
            )


__all__ = ["OpportunityWorkflow"]