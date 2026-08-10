"""Application service and workers for controlled workspace agents."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domains.agent.models import AgentArtifact, AgentRun, AgentStep
from app.domains.chat.models import ChatConversation, ChatMessage, ChatMessageEvidence
from app.domains.chat.service import ChatService
from app.domains.discover.models import (
    OpportunityEvidence,
    OpportunityVersion,
    ResearchOpportunity,
    ResearchPlan,
)
from app.domains.retrieval.service import semantic_search
from app.domains.task.models import Task
from app.domains.task.schemas import TaskCreate
from app.domains.task.service import TaskService
from app.domains.workspace.service import WorkspaceService
from app.gateway.llm import LLMGateway, get_llm_gateway


class AgentRunNotFoundError(LookupError):
    pass


class AgentInputError(ValueError):
    pass


class AgentConflictError(RuntimeError):
    pass


class AgentExecutionDisabledError(RuntimeError):
    pass


ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}

# W7 full-lifecycle agents share the same controlled-run protocol.
SUPPORTED_AGENT_TYPES = {
    "research_plan",
    "code_generation",
    "analyze",
    "write",
    "respond",
}
# Agents that must be attached to an existing research plan.
PLAN_BOUND_AGENT_TYPES = {"code_generation", "analyze", "write", "respond"}


class AgentService:
    def __init__(self, db: Session, gateway: LLMGateway | None = None) -> None:
        self.db = db
        self.gateway = gateway

    def start(
        self,
        workspace_id: str,
        *,
        agent_type: str,
        prompt: str,
        conversation_id: str,
        input_payload: dict[str, Any] | None = None,
    ) -> AgentRun:
        workspace = WorkspaceService(self.db).get(workspace_id)
        conversation = self.db.get(ChatConversation, conversation_id)
        if conversation is None or conversation.is_deleted:
            raise AgentInputError("对话不存在")
        if conversation.workspace_id != workspace_id:
            raise AgentInputError("Agent 对话与工作区不匹配")
        if agent_type not in SUPPORTED_AGENT_TYPES:
            raise AgentInputError("不支持的 Agent 类型")
        payload = dict(input_payload or {})
        payload["prompt"] = prompt.strip()
        if not payload["prompt"]:
            raise AgentInputError("任务描述不能为空")
        if agent_type in PLAN_BOUND_AGENT_TYPES:
            plan_id = str(payload.get("research_plan_id") or "")
            plan = self.db.get(ResearchPlan, plan_id) if plan_id else None
            if plan is None or plan.workspace_id != workspace_id:
                raise AgentInputError("该 Agent 必须选择当前工作区中的研究计划")
        if agent_type == "respond" and not str(payload.get("reviewer_comments") or "").strip():
            raise AgentInputError("审稿回复必须提供审稿意见")

        active = self.db.scalar(
            select(AgentRun.id)
            .where(
                AgentRun.conversation_id == conversation_id,
                AgentRun.status.in_(ACTIVE_STATUSES),
            )
            .limit(1)
        )
        if active:
            raise AgentConflictError("当前对话已有 Agent 正在运行")

        task = TaskService(self.db).create(
            TaskCreate(workspace_id=workspace_id, task_type=f"agent_{agent_type}", payload={})
        )
        sequence = (
            int(
                self.db.scalar(
                    select(func.max(ChatMessage.sequence)).where(
                        ChatMessage.conversation_id == conversation_id
                    )
                )
                or 0
            )
            + 1
        )
        user_message = ChatMessage(
            conversation_id=conversation_id,
            role="user",
            content=payload["prompt"],
            status="completed",
            sequence=sequence,
            grounding_status="not_requested",
        )
        assistant_message = ChatMessage(
            conversation_id=conversation_id,
            role="assistant",
            content="",
            status="generating",
            sequence=sequence + 1,
            grounding_status="not_requested",
        )
        self.db.add_all([user_message, assistant_message])
        self.db.flush()
        context_snapshot: dict[str, Any] = {"workspace_name": workspace.name}
        if plan is not None:
            context_snapshot["research_plan"] = self._plan_snapshot(plan)
        run = AgentRun(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            trigger_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            task_id=task.id,
            agent_type=agent_type,
            status="queued",
            current_stage="queued",
            progress=0.0,
            input_payload=payload,
            context_snapshot=context_snapshot,
            requires_confirmation=agent_type in {"research_plan", "deep_research"},
        )
        self.db.add(run)
        self.db.flush()
        task.payload = {"agent_run_id": run.id, "agent_type": agent_type}
        conversation.last_message_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(run)
        return run

    def get(self, workspace_id: str, run_id: str) -> AgentRun:
        run = self.db.get(AgentRun, run_id)
        if run is None or run.workspace_id != workspace_id:
            raise AgentRunNotFoundError("Agent 运行不存在")
        return run

    def list(
        self,
        workspace_id: str,
        *,
        conversation_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[AgentRun], int]:
        WorkspaceService(self.db).get(workspace_id)
        stmt = select(AgentRun).where(AgentRun.workspace_id == workspace_id)
        if conversation_id:
            stmt = stmt.where(AgentRun.conversation_id == conversation_id)
        total = int(self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        items = list(
            self.db.scalars(stmt.order_by(AgentRun.created_at.desc()).offset(offset).limit(limit))
        )
        return items, total

    def detail(
        self, workspace_id: str, run_id: str
    ) -> tuple[AgentRun, list[AgentStep], list[AgentArtifact]]:
        run = self.get(workspace_id, run_id)
        steps = list(
            self.db.scalars(
                select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.sequence)
            )
        )
        artifacts = list(
            self.db.scalars(
                select(AgentArtifact)
                .where(
                    AgentArtifact.run_id == run.id,
                    AgentArtifact.is_deleted.is_(False),
                )
                .order_by(AgentArtifact.filename)
            )
        )
        return run, steps, artifacts

    def cancel(self, workspace_id: str, run_id: str) -> AgentRun:
        run = self.get(workspace_id, run_id)
        if run.status not in ACTIVE_STATUSES and run.status != "waiting_for_user":
            raise AgentConflictError("当前 Agent 状态不能取消")
        if run.task_id:
            TaskService(self.db).request_cancel(run.task_id)
        run.status = "cancelled"
        run.current_stage = "cancelled"
        self._finish_assistant(run, "Agent 任务已取消。", failed=False)
        self.db.commit()
        return run

    def mark_dispatch_failed(self, run_id: str, message: str) -> None:
        run = self.db.get(AgentRun, run_id)
        if run is None:
            return
        self._fail(run, f"任务调度失败：{message}")

    def execute(self, run_id: str) -> dict[str, Any]:
        run = self.db.get(AgentRun, run_id)
        if run is None:
            raise AgentRunNotFoundError("Agent 运行不存在")
        if run.status == "cancelled":
            return {"status": "cancelled"}
        try:
            self._transition(run, "running", "preflight", 0.05)
            if run.agent_type == "research_plan":
                return self._execute_research_plan(run)
            if run.agent_type == "deep_research":
                return self._execute_deep_research(run)
            if run.agent_type == "code_generation":
                return self._execute_code_generation(run)
            if run.agent_type == "analyze":
                return self._execute_analyze(run)
            if run.agent_type == "write":
                return self._execute_write(run)
            if run.agent_type == "respond":
                return self._execute_respond(run)
            raise AgentInputError("不支持的 Agent 类型")
        except Exception as exc:
            self.db.rollback()
            run = self.db.get(AgentRun, run_id)
            if run is not None and run.status != "cancelled":
                self._fail(run, self._safe_error(exc))
            raise

    def confirm(self, workspace_id: str, run_id: str) -> tuple[AgentRun, ResearchPlan | None]:
        run = self.get(workspace_id, run_id)
        if run.status != "waiting_for_user" or run.agent_type not in {
            "research_plan",
            "deep_research",
        }:
            raise AgentConflictError("只有等待审核的 Agent 产物可以确认")
        result = dict(run.result or {})
        plan: ResearchPlan | None = None
        if run.agent_type == "research_plan":
            target_plan_id = str(run.input_payload.get("research_plan_id") or "")
            plan = self.db.get(ResearchPlan, target_plan_id) if target_plan_id else None
            if plan is not None and plan.workspace_id != workspace_id:
                raise AgentInputError("待完善的研究计划不属于当前工作区")
            if plan is None:
                plan = self.db.scalar(
                    select(ResearchPlan).where(ResearchPlan.agent_run_id == run.id)
                )
        if run.agent_type == "research_plan" and plan is None:
            opportunity_id = result.get("opportunity_id")
            version_id = result.get("opportunity_version_id")
            plan = ResearchPlan(
                workspace_id=workspace_id,
                opportunity_id=opportunity_id or None,
                opportunity_version_id=version_id or None,
                agent_run_id=run.id,
                source_type="agent",
                status="draft",
                title=str(result.get("title") or "未命名研究计划"),
                research_question=str(result.get("research_question") or ""),
                hypothesis=str(result.get("hypothesis") or ""),
                scope_and_assumptions=str(result.get("scope_and_assumptions") or ""),
                datasets=self._string_list(result.get("datasets")),
                baselines=self._string_list(result.get("baselines")),
                metrics=self._string_list(result.get("metrics")),
                validation_steps=self._string_list(result.get("validation_steps")),
                expected_supporting_result=str(result.get("expected_supporting_result") or ""),
                falsification_criteria=str(result.get("falsification_criteria") or ""),
                risks=self._string_list(result.get("risks")),
                resource_constraints=str(result.get("resource_constraints") or ""),
            )
            self.db.add(plan)
            self.db.flush()
        elif run.agent_type == "research_plan" and plan is not None:
            plan.agent_run_id = run.id
            plan.source_type = "agent_refined"
            plan.status = "draft"
            plan.title = str(result.get("title") or plan.title or "未命名研究计划")
            plan.research_question = str(result.get("research_question") or plan.research_question)
            plan.hypothesis = str(result.get("hypothesis") or plan.hypothesis)
            plan.scope_and_assumptions = str(
                result.get("scope_and_assumptions") or plan.scope_and_assumptions
            )
            plan.datasets = self._string_list(result.get("datasets")) or list(plan.datasets)
            plan.baselines = self._string_list(result.get("baselines")) or list(plan.baselines)
            plan.metrics = self._string_list(result.get("metrics")) or list(plan.metrics)
            plan.validation_steps = self._string_list(result.get("validation_steps")) or list(
                plan.validation_steps
            )
            plan.expected_supporting_result = str(
                result.get("expected_supporting_result") or plan.expected_supporting_result
            )
            plan.falsification_criteria = str(
                result.get("falsification_criteria") or plan.falsification_criteria
            )
            plan.risks = self._string_list(result.get("risks")) or list(plan.risks)
            plan.resource_constraints = str(
                result.get("resource_constraints") or plan.resource_constraints
            )
            self.db.flush()
        elif run.agent_type == "deep_research":
            plan = self.db.get(ResearchPlan, str(run.input_payload.get("research_plan_id") or ""))
            if plan is None or plan.workspace_id != workspace_id:
                raise AgentInputError("深度研究绑定的研究计划不存在")
        for artifact in self.db.scalars(
            select(AgentArtifact).where(AgentArtifact.run_id == run.id)
        ):
            artifact.validation_status = "confirmed"
        if run.task_id:
            task_service = TaskService(self.db)
            task_service.resume_from_user(run.task_id, decision={"action": "confirm"})
            task_service.transition(
                run.task_id,
                "succeeded",
                progress=1.0,
                result={"research_plan_id": plan.id if plan else None, "agent_run_id": run.id},
            )
        run.status = "succeeded"
        run.current_stage = "saved"
        run.progress = 1.0
        run.requires_confirmation = False
        result["research_plan_id"] = plan.id if plan else None
        if run.agent_type == "deep_research":
            result["review_status"] = "confirmed"
        run.result = result
        if run.agent_type == "deep_research":
            message = "深度研究报告已通过人工确认，并保存到研究中心。"
        else:
            message = f"研究计划已确认并保存到研究中心。\n\n**研究问题：** {plan.research_question}"
        self._finish_assistant(run, message, failed=False)
        self.db.commit()
        self.db.refresh(run)
        self.db.refresh(plan)
        return run, plan

    def artifact(self, workspace_id: str, run_id: str, artifact_id: str) -> AgentArtifact:
        self.get(workspace_id, run_id)
        artifact = self.db.get(AgentArtifact, artifact_id)
        if artifact is None or artifact.run_id != run_id or artifact.is_deleted:
            raise AgentRunNotFoundError("Agent 产物不存在")
        return artifact

    def request_code_validation(self, workspace_id: str, run_id: str) -> Task:
        run = self.get(workspace_id, run_id)
        if run.agent_type != "code_generation" or run.status != "succeeded":
            raise AgentConflictError("只有已完成的代码生成任务可以验证")
        if not settings.agent_code_execution_enabled:
            raise AgentExecutionDisabledError(
                "代码验证默认关闭；如需启用，请设置 AGENT_CODE_EXECUTION_ENABLED=true"
            )
        existing = self.db.scalar(
            select(Task)
            .where(
                Task.workspace_id == workspace_id,
                Task.task_type == "validate_agent_code",
                Task.status.in_({"queued", "running"}),
            )
            .order_by(Task.created_at.desc())
        )
        if existing and str((existing.payload or {}).get("agent_run_id")) == run.id:
            raise AgentConflictError("该代码任务正在验证")
        return TaskService(self.db).create(
            TaskCreate(
                workspace_id=workspace_id,
                task_type="validate_agent_code",
                payload={"agent_run_id": run.id},
            )
        )

    def _execute_research_plan(self, run: AgentRun) -> dict[str, Any]:
        self._step(run, 1, "workspace_retrieval", "running", "正在检索工作区证据")
        evidence = self._retrieve(run, str(run.input_payload.get("prompt") or ""))
        if not evidence:
            raise AgentInputError("当前工作区没有可用于生成研究计划的已索引论文内容")
        self._step(run, 1, "workspace_retrieval", "completed", f"已选取 {len(evidence)} 条证据")
        self._transition(run, "running", "plan_synthesis", 0.45)
        opportunity_context = self._opportunity_context(run)
        prompt = self._research_plan_prompt(run, evidence, opportunity_context)
        result, usage = self._structured_completion(prompt, max_tokens=2600)
        normalized = self._normalize_plan(result, run, opportunity_context)
        run.context_snapshot = {
            **dict(run.context_snapshot or {}),
            "evidence": evidence,
            "opportunity": opportunity_context,
        }
        run.result = normalized
        self._step(run, 2, "plan_synthesis", "completed", "已生成结构化研究计划草案", usage)
        self._step(
            run,
            3,
            "evidence_gate",
            "completed",
            "关键计划字段已绑定工作区证据",
            {"evidence_count": len(evidence)},
        )
        artifact = AgentArtifact(
            run_id=run.id,
            artifact_type="research_plan",
            filename="research_plan.md",
            mime_type="text/markdown",
            content=self._plan_markdown(normalized, evidence),
            metadata_payload={"evidence_count": len(evidence)},
            validation_status="pending_review",
        )
        self.db.add(artifact)
        run.status = "waiting_for_user"
        run.current_stage = "human_review"
        run.progress = 0.9
        run.requires_confirmation = True
        if run.task_id:
            TaskService(self.db).transition(
                run.task_id,
                "waiting_for_user",
                progress=0.9,
                result={"agent_run_id": run.id, "artifact": "research_plan.md"},
            )
        self._finish_assistant(
            run,
            f"研究计划草案已生成，等待确认。\n\n**研究问题：** {normalized['research_question']}\n\n"
            f"**核心假设：** {normalized['hypothesis']}",
            failed=False,
        )
        self.db.commit()
        return {"status": run.status, "run_id": run.id}

    def _execute_deep_research(self, run: AgentRun) -> dict[str, Any]:
        plan = self.db.get(ResearchPlan, str(run.input_payload.get("research_plan_id") or ""))
        if plan is None or plan.workspace_id != run.workspace_id:
            raise AgentInputError("深度研究绑定的研究计划不存在或不属于当前工作区")
        plan_snapshot = dict((run.context_snapshot or {}).get("research_plan") or {})
        if not plan_snapshot:
            plan_snapshot = self._plan_snapshot(plan)
        self._step(
            run,
            1,
            "plan_binding",
            "completed",
            "已固定研究计划与机会版本快照",
            {
                "research_plan_id": plan.id,
                "opportunity_version_id": plan_snapshot.get("opportunity_version_id"),
            },
        )

        query = " ".join(
            part
            for part in (
                str(plan_snapshot.get("title") or ""),
                str(plan_snapshot.get("research_question") or ""),
                str(plan_snapshot.get("hypothesis") or ""),
                str(run.input_payload.get("prompt") or ""),
            )
            if part
        )
        workspace_evidence = self._retrieve(run, query)
        if not workspace_evidence:
            raise AgentInputError("当前工作区没有可用于深度研究的已索引论文内容")
        for index, item in enumerate(workspace_evidence, 1):
            item["evidence_id"] = f"W{index}"
            item["relation"] = "workspace_retrieval"
            item["source_scope"] = "workspace"
        discover_evidence = self._discover_evidence(plan_snapshot)
        evidence = discover_evidence + workspace_evidence
        self._step(
            run,
            2,
            "evidence_collection",
            "completed",
            f"已汇集 {len(evidence)} 条可追溯证据",
            {
                "discover_evidence_count": len(discover_evidence),
                "workspace_evidence_count": len(workspace_evidence),
            },
        )

        self._transition(run, "running", "deep_synthesis", 0.55)
        prompt = self._deep_research_prompt(run, plan_snapshot, evidence)
        raw, usage = self._structured_completion(prompt, max_tokens=5200)
        normalized = self._normalize_deep_research(raw, plan_snapshot, evidence)
        run.context_snapshot = {
            **dict(run.context_snapshot or {}),
            "research_plan": plan_snapshot,
            "evidence": evidence,
        }
        run.result = normalized
        self._step(run, 3, "deep_synthesis", "completed", "已生成深度研究报告草案", usage)
        self._step(
            run,
            4,
            "evidence_gate",
            "completed",
            "报告结论已绑定可追溯证据",
            {"evidence_refs": normalized["evidence_refs"]},
        )
        self.db.add(
            AgentArtifact(
                run_id=run.id,
                artifact_type="deep_research_report",
                filename="deep_research_report.md",
                mime_type="text/markdown",
                content=self._deep_research_markdown(normalized, evidence),
                metadata_payload={
                    "research_plan_id": plan.id,
                    "opportunity_version_id": plan_snapshot.get("opportunity_version_id"),
                    "evidence_count": len(evidence),
                },
                validation_status="pending_review",
            )
        )
        run.status = "waiting_for_user"
        run.current_stage = "human_review"
        run.progress = 0.9
        run.requires_confirmation = True
        if run.task_id:
            TaskService(self.db).transition(
                run.task_id,
                "waiting_for_user",
                progress=0.9,
                result={"agent_run_id": run.id, "artifact": "deep_research_report.md"},
            )
        self._finish_assistant(
            run,
            f"深度研究报告草案已生成，等待人工确认。\n\n**核心结论：** {normalized['executive_summary']}",
            failed=False,
        )
        self.db.commit()
        return {"status": run.status, "run_id": run.id}

    def _execute_code_generation(self, run: AgentRun) -> dict[str, Any]:
        plan = self.db.get(ResearchPlan, str(run.input_payload.get("research_plan_id") or ""))
        if plan is None or plan.workspace_id != run.workspace_id:
            raise AgentInputError("研究计划不存在或不属于当前工作区")
        self._step(run, 1, "workspace_retrieval", "running", "正在检索方法与实验细节")
        evidence = self._retrieve(run, f"{plan.research_question} {plan.hypothesis}")
        if not evidence:
            raise AgentInputError("当前工作区没有已索引证据，不能生成有依据的实验代码")
        self._step(run, 1, "workspace_retrieval", "completed", f"已选取 {len(evidence)} 条证据")
        self._transition(run, "running", "code_generation", 0.4)
        prompt = self._code_prompt(run, plan, evidence)
        raw, usage = self._structured_completion(prompt, max_tokens=7000)
        files = self._normalize_files(raw.get("files"))
        if not files:
            raise AgentInputError("模型没有返回有效代码文件")
        for file in files:
            self.db.add(
                AgentArtifact(
                    run_id=run.id,
                    artifact_type="code",
                    filename=file["path"],
                    mime_type=self._mime_type(file["path"]),
                    content=file["content"],
                    metadata_payload={"language": file.get("language", "text")},
                    validation_status="not_run",
                )
            )
        run.context_snapshot = {
            **dict(run.context_snapshot or {}),
            "research_plan_id": plan.id,
            "evidence": evidence,
        }
        run.result = {
            "research_plan_id": plan.id,
            "summary": str(raw.get("summary") or "实验代码项目已生成"),
            "file_count": len(files),
            "validation": {"status": "not_run"},
        }
        self._step(run, 2, "code_generation", "completed", f"已生成 {len(files)} 个文件", usage)
        self._step(run, 3, "static_review", "completed", "文件路径和产物规模检查通过")
        run.status = "succeeded"
        run.current_stage = "artifacts_ready"
        run.progress = 1.0
        if run.task_id:
            TaskService(self.db).transition(
                run.task_id,
                "succeeded",
                progress=1.0,
                result={"agent_run_id": run.id, "file_count": len(files)},
            )
        self._finish_assistant(
            run,
            f"代码生成完成，共生成 **{len(files)}** 个文件。你可以预览单个文件或下载完整 ZIP。",
            failed=False,
        )
        self.db.commit()
        return {"status": run.status, "run_id": run.id, "file_count": len(files)}

    # ----------------------------------------------------- W7 lifecycle agents
    # Analyze / Write / Respond are lightweight, evidence-linked, controlled
    # agents. They follow the same AgentRun/AgentStep/AgentArtifact protocol,
    # keep their outputs in agent_artifacts (never auto-promoted to facts),
    # end in "succeeded" (no confirmation gate - HITL reviews the artifacts),
    # and every claim cites workspace evidence via [En] markers.

    def _bound_plan(self, run: AgentRun) -> ResearchPlan:
        plan = self.db.get(ResearchPlan, str(run.input_payload.get("research_plan_id") or ""))
        if plan is None or plan.workspace_id != run.workspace_id:
            raise AgentInputError("研究计划不存在或不属于当前工作区")
        return plan

    def _execute_analyze(self, run: AgentRun) -> dict[str, Any]:
        """AnalyzeAgent: user-uploaded experiment results vs the plan's
        falsification criteria, producing a support / partial / reject verdict
        with evidence-linked findings. Eats manual data (results are supplied
        by the user, never auto-run experiments)."""
        plan = self._bound_plan(run)
        self._step(run, 1, "workspace_retrieval", "running", "正在检索相关证据")
        evidence = self._retrieve(run, f"{plan.research_question} {plan.hypothesis} {plan.falsification_criteria}")
        self._step(run, 1, "workspace_retrieval", "completed", f"已选取 {len(evidence)} 条证据")
        self._transition(run, "running", "analysis", 0.45)
        prompt = self._analysis_prompt(run, plan, evidence)
        raw, usage = self._structured_completion(prompt, max_tokens=2600)
        normalized = self._normalize_analysis(raw)
        run.context_snapshot = {**dict(run.context_snapshot or {}), "research_plan_id": plan.id, "evidence": evidence}
        run.result = {"research_plan_id": plan.id, **normalized}
        self._step(run, 2, "analysis", "completed", f"已得出“{normalized['verdict']}”结论", usage)
        self._step(run, 3, "saved", "completed", "结果分析已产出，关键结论回链证据", {"evidence_count": len(evidence)})
        self.db.add(
            AgentArtifact(
                run_id=run.id,
                artifact_type="analysis",
                filename="research_memo.md",
                mime_type="text/markdown",
                content=self._analysis_markdown(normalized, evidence),
                metadata_payload={"research_plan_id": plan.id, "verdict": normalized["verdict"]},
                validation_status="unreviewed",
            )
        )
        return self._finish_artifacts_ready(
            run,
            f"结果分析完成，结论：**{normalized['verdict']}**。产物 `research_memo.md` 已生成，可预览查看。",
        )

    def _execute_write(self, run: AgentRun) -> dict[str, Any]:
        """WriteAgent: plan + evidence -> paper section drafts."""
        plan = self._bound_plan(run)
        self._step(run, 1, "workspace_retrieval", "running", "正在检索方法与相关证据")
        evidence = self._retrieve(run, f"{plan.research_question} {plan.hypothesis} {plan.scope_and_assumptions}")
        self._step(run, 1, "workspace_retrieval", "completed", f"已选取 {len(evidence)} 条证据")
        self._transition(run, "running", "paper_writing", 0.45)
        prompt = self._draft_prompt(run, plan, evidence)
        raw, usage = self._structured_completion(prompt, max_tokens=4000)
        normalized = self._normalize_draft(raw)
        run.context_snapshot = {**dict(run.context_snapshot or {}), "research_plan_id": plan.id, "evidence": evidence}
        run.result = {"research_plan_id": plan.id, **normalized}
        self._step(run, 2, "paper_writing", "completed", f"已生成论文草稿（{len(normalized['sections'])} 个章节）", usage)
        self._step(run, 3, "saved", "completed", "论文草稿已产出，引用回链证据", {"evidence_count": len(evidence)})
        self.db.add(
            AgentArtifact(
                run_id=run.id,
                artifact_type="paper_draft",
                filename="paper_draft.md",
                mime_type="text/markdown",
                content=self._draft_markdown(normalized, evidence),
                metadata_payload={"research_plan_id": plan.id, "title": normalized["title"]},
                validation_status="unreviewed",
            )
        )
        return self._finish_artifacts_ready(
            run,
            f"论文草稿已生成：**{normalized['title']}**。产物 `paper_draft.md` 已生成，可预览查看。",
        )

    def _execute_respond(self, run: AgentRun) -> dict[str, Any]:
        """RespondAgent: reviewer comments -> per-point rebuttal draft."""
        plan = self._bound_plan(run)
        comments = str(run.input_payload.get("reviewer_comments") or "")
        self._step(run, 1, "workspace_retrieval", "running", "正在检索相关证据")
        evidence = self._retrieve(run, f"{plan.research_question} {plan.hypothesis}")
        self._step(run, 1, "workspace_retrieval", "completed", f"已选取 {len(evidence)} 条证据")
        self._transition(run, "running", "rebuttal", 0.45)
        prompt = self._rebuttal_prompt(run, plan, comments, evidence)
        raw, usage = self._structured_completion(prompt, max_tokens=3000)
        normalized = self._normalize_rebuttal(raw)
        run.context_snapshot = {**dict(run.context_snapshot or {}), "research_plan_id": plan.id, "evidence": evidence}
        run.result = {"research_plan_id": plan.id, **normalized}
        self._step(run, 2, "rebuttal", "completed", f"已生成 {len(normalized['responses'])} 条审稿回复", usage)
        self._step(run, 3, "saved", "completed", "审稿回复已产出，回复依据回链证据", {"response_count": len(normalized["responses"])})
        self.db.add(
            AgentArtifact(
                run_id=run.id,
                artifact_type="rebuttal",
                filename="rebuttal.md",
                mime_type="text/markdown",
                content=self._rebuttal_markdown(normalized, evidence),
                metadata_payload={"research_plan_id": plan.id, "response_count": len(normalized["responses"])},
                validation_status="unreviewed",
            )
        )
        return self._finish_artifacts_ready(
            run,
            f"审稿回复完成，共 **{len(normalized['responses'])}** 条逐条回应。产物 `rebuttal.md` 已生成。",
        )

    def _finish_artifacts_ready(self, run: AgentRun, message: str) -> dict[str, Any]:
        run.status = "succeeded"
        run.current_stage = "artifacts_ready"
        run.progress = 1.0
        if run.task_id:
            TaskService(self.db).transition(
                run.task_id, "succeeded", progress=1.0, result={"agent_run_id": run.id}
            )
        self._finish_assistant(run, message, failed=False)
        self.db.commit()
        return {"status": run.status, "run_id": run.id}

    # ---------------------------------------------------------------- prompts
    def _analysis_prompt(self, run: AgentRun, plan: ResearchPlan, evidence: list[dict[str, Any]]) -> str:
        results = run.input_payload.get("results") or {}
        return (
            "你是结果分析 agent。用户上传了实验结果，请对照研究计划的证伪标准、指标与预期支持结果，"
            "判定结论。结论必须引用 evidence_id（[En] 标记，仅引用真实存在的证据）。"
            "返回 JSON：verdict(支持|部分支持|否定|证据不足), conclusion, key_findings(string[]), "
            "evidence_refs(string[]), risks(string[])。\n\n"
            f"实验 JSON：{json.dumps(results, ensure_ascii=False)[:6000]}\n"
            f"研究问题：{plan.research_question}\n核心假设：{plan.hypothesis}\n"
            f"证伪标准：{plan.falsification_criteria}\n指标：{json.dumps(plan.metrics, ensure_ascii=False)}\n"
            f"验证步骤：{json.dumps(plan.validation_steps, ensure_ascii=False)}\n"
            f"预期支持结果：{plan.expected_supporting_result}\n"
            f"证据：{json.dumps(evidence, ensure_ascii=False)}"
        )

    def _draft_prompt(self, run: AgentRun, plan: ResearchPlan, evidence: list[dict[str, Any]]) -> str:
        plan_payload = {
            "research_question": plan.research_question,
            "hypothesis": plan.hypothesis,
            "scope_and_assumptions": plan.scope_and_assumptions,
            "datasets": plan.datasets,
            "baselines": plan.baselines,
            "metrics": plan.metrics,
            "validation_steps": plan.validation_steps,
            "expected_supporting_result": plan.expected_supporting_result,
            "risks": plan.risks,
        }
        return (
            "你是论文写作 agent。基于研究计划与工作区证据生成论文章节草稿。英文标题，正文用中文草稿，"
            "关键论断用 [En] 标记引用证据（仅引用真实存在的 evidence_id）。"
            "返回 JSON：title, abstract, introduction, method, experiments, conclusion, "
            "evidence_refs(string[])。\n\n"
            f"用户要求：{run.input_payload.get('prompt')}\n"
            f"研究计划：{json.dumps(plan_payload, ensure_ascii=False)}\n"
            f"证据：{json.dumps(evidence, ensure_ascii=False)}"
        )

    def _rebuttal_prompt(self, run: AgentRun, plan: ResearchPlan, comments: str, evidence: list[dict[str, Any]]) -> str:
        return (
            "你是审稿回复 agent。对每条审稿意见给出逐条回应，回应需给出依据并回链证据 [En]。"
            "返回 JSON：responses([{comment, response, evidence_refs(string[])}]), summary, "
            "evidence_refs(string[])。\n\n"
            f"审稿意见：{comments[:4000]}\n"
            f"研究计划：研究问题 {plan.research_question}；假设 {plan.hypothesis}；"
            f"证伪标准 {plan.falsification_criteria}；数据集 {json.dumps(plan.datasets, ensure_ascii=False)}\n"
            f"证据：{json.dumps(evidence, ensure_ascii=False)}"
        )

    # -------------------------------------------------------------- normalize
    def _normalize_analysis(self, data: dict[str, Any]) -> dict[str, Any]:
        verdict = str(data.get("verdict") or "证据不足")
        if verdict not in {"支持", "部分支持", "否定", "证据不足"}:
            verdict = "证据不足"
        return {
            "verdict": verdict,
            "conclusion": str(data.get("conclusion") or "实验数据不足以得出明确结论。"),
            "key_findings": self._string_list(data.get("key_findings")),
            "evidence_refs": self._string_list(data.get("evidence_refs")),
            "risks": self._string_list(data.get("risks")),
        }

    def _normalize_draft(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": str(data.get("title") or "研究论文草稿"),
            "abstract": str(data.get("abstract") or ""),
            "introduction": str(data.get("introduction") or ""),
            "method": str(data.get("method") or ""),
            "experiments": str(data.get("experiments") or ""),
            "conclusion": str(data.get("conclusion") or ""),
            "evidence_refs": self._string_list(data.get("evidence_refs")),
            "sections": ["abstract", "introduction", "method", "experiments", "conclusion"],
        }

    def _normalize_rebuttal(self, data: dict[str, Any]) -> dict[str, Any]:
        responses: list[dict[str, Any]] = []
        for raw in data.get("responses") or []:
            if not isinstance(raw, dict):
                continue
            comment = str(raw.get("comment") or "").strip()
            if not comment:
                continue
            responses.append(
                {
                    "comment": comment,
                    "response": str(raw.get("response") or ""),
                    "evidence_refs": self._string_list(raw.get("evidence_refs")),
                }
            )
        return {
            "summary": str(data.get("summary") or ""),
            "responses": responses,
            "evidence_refs": self._string_list(data.get("evidence_refs")),
        }

    # -------------------------------------------------------------- markdown
    @staticmethod
    def _bullets(values: list[str]) -> str:
        return "\n".join(f"- {value}" for value in values) or "- 暂无"

    @staticmethod
    def _evidence_sources(evidence: list[dict[str, Any]]) -> str:
        return "\n".join(
            f"- [{item['evidence_id']}] {item.get('paper_title') or '未命名论文'} / {item.get('section') or '未知章节'}"
            for item in evidence
        ) or "- 无"

    @classmethod
    def _analysis_markdown(cls, result: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
        return (
            f"# 结果分析\n\n## 结论\n{result['verdict']}\n\n## 分析\n{result['conclusion']}\n\n"
            f"## 关键发现\n{cls._bullets(result['key_findings'])}\n\n"
            f"## 风险\n{cls._bullets(result['risks'])}\n\n## 证据来源\n{cls._evidence_sources(evidence)}\n"
        )

    @classmethod
    def _draft_markdown(cls, result: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
        return (
            f"# {result['title']}\n\n## Abstract\n{result['abstract']}\n\n"
            f"## Introduction\n{result['introduction']}\n\n## Method\n{result['method']}\n\n"
            f"## Experiments\n{result['experiments']}\n\n## Conclusion\n{result['conclusion']}\n\n"
            f"## 证据来源\n{cls._evidence_sources(evidence)}\n"
        )

    @classmethod
    def _rebuttal_markdown(cls, result: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
        points = "\n\n".join(
            f"### 意见 {index + 1}\n> {r['comment']}\n\n回复：{r['response']}\n"
            f"依据：{' '.join(f'[{ref}]' for ref in r['evidence_refs']) or '无'}"
            for index, r in enumerate(result["responses"])
        )
        summary = f"## 总结\n{result['summary']}\n\n" if result["summary"] else ""
        return f"# 审稿回复草稿\n\n{summary}{points}\n\n## 证据来源\n{cls._evidence_sources(evidence)}\n"

    def _retrieve(self, run: AgentRun, query: str) -> list[dict[str, Any]]:
        self._transition(run, "running", "workspace_retrieval", 0.18)
        response = semantic_search(
            workspace_id=run.workspace_id,
            query=query,
            top_k=max(settings.agent_rag_top_k, 1),
            use_reranker=True,
        )
        if response.status == "failed":
            raise AgentInputError(response.error or "工作区检索失败")
        if run.assistant_message_id and not self.db.scalar(
            select(ChatMessageEvidence.id)
            .where(ChatMessageEvidence.message_id == run.assistant_message_id)
            .limit(1)
        ):
            workspace = WorkspaceService(self.db).get(run.workspace_id)
            citations = ChatService(self.db)._materialize_evidence(
                workspace,
                run.assistant_message_id,
                response.items,
            )
            self.db.add_all(citations)
            self.db.flush()
        evidence: list[dict[str, Any]] = []
        for index, item in enumerate(response.items, 1):
            text = ChatService._postgres_safe_text(item.text).strip()
            if not item.paper_id or not text:
                continue
            evidence.append(
                {
                    "evidence_id": f"E{index}",
                    "paper_id": item.paper_id,
                    "paper_title": ChatService._postgres_safe_text(item.paper_title) or None,
                    "chunk_id": ChatService._postgres_safe_text(item.chunk_id) or None,
                    "section": ChatService._postgres_safe_text(item.section) or None,
                    "score": round(float(item.score), 4),
                    "text": text[:3000],
                }
            )
        return evidence

    def _opportunity_context(self, run: AgentRun) -> dict[str, Any] | None:
        opportunity_id = str(run.input_payload.get("opportunity_id") or "")
        if not opportunity_id and run.input_payload.get("research_plan_id"):
            target_plan = self.db.get(
                ResearchPlan, str(run.input_payload.get("research_plan_id") or "")
            )
            if target_plan and target_plan.workspace_id == run.workspace_id:
                opportunity_id = str(target_plan.opportunity_id or "")
        if not opportunity_id:
            return None
        opportunity = self.db.get(ResearchOpportunity, opportunity_id)
        if (
            opportunity is None
            or opportunity.is_deleted
            or opportunity.workspace_id != run.workspace_id
            or opportunity.status not in {"confirmed", "edited_confirmed"}
        ):
            raise AgentInputError("只能使用当前工作区中已确认的研究机会")
        version = self.db.get(OpportunityVersion, opportunity.current_version_id)
        return {
            "opportunity_id": opportunity.id,
            "opportunity_version_id": version.id if version else None,
            "title": opportunity.title,
            "research_question": version.candidate_research_question if version else "",
            "hypothesis": version.candidate_hypothesis if version else "",
            "scope": version.research_scope if version else "",
            "validation_plan": version.candidate_validation_plan if version else {},
            "risks": version.open_risks if version else [],
        }

    @staticmethod
    def _plan_snapshot(plan: ResearchPlan) -> dict[str, Any]:
        return {
            "research_plan_id": plan.id,
            "opportunity_id": plan.opportunity_id,
            "opportunity_version_id": plan.opportunity_version_id,
            "title": plan.title,
            "research_question": plan.research_question,
            "hypothesis": plan.hypothesis,
            "scope_and_assumptions": plan.scope_and_assumptions,
            "datasets": list(plan.datasets),
            "baselines": list(plan.baselines),
            "metrics": list(plan.metrics),
            "validation_steps": list(plan.validation_steps),
            "expected_supporting_result": plan.expected_supporting_result,
            "falsification_criteria": plan.falsification_criteria,
            "risks": list(plan.risks),
            "resource_constraints": plan.resource_constraints,
        }

    def _discover_evidence(self, plan_snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        version_id = str(plan_snapshot.get("opportunity_version_id") or "")
        if not version_id:
            return []
        rows = list(
            self.db.scalars(
                select(OpportunityEvidence)
                .where(OpportunityEvidence.opportunity_version_id == version_id)
                .order_by(
                    OpportunityEvidence.rank.asc().nullslast(), OpportunityEvidence.created_at
                )
            )
        )
        return [
            {
                "evidence_id": f"D{index}",
                "paper_id": item.paper_id,
                "paper_title": str(
                    (item.snapshot_payload or {}).get("paper_title") or "外部或已核验证据"
                ),
                "section": str((item.snapshot_payload or {}).get("section") or "Discover 核验证据"),
                "relation": item.relation,
                "source_scope": item.source_scope,
                "evidence_level": item.evidence_level,
                "score": round(float(item.score or 0), 4),
                "text": item.display_excerpt[:3000],
            }
            for index, item in enumerate(rows, 1)
            if item.display_excerpt.strip()
        ]

    def _structured_completion(
        self, user_prompt: str, *, max_tokens: int
    ) -> tuple[dict[str, Any], dict[str, int]]:
        gateway = self.gateway or get_llm_gateway()
        if not getattr(gateway, "api_key", None):
            raise AgentInputError("DeepSeek API key is not configured")
        response = gateway.chat_completion(
            [
                {
                    "role": "system",
                    "content": (
                        "你是一个受控科研智能体。除代码字段外使用中文，只返回有效 JSON，"
                        "绝不编造证据。"
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            disable_thinking=True,
        )
        parsed = self._parse_json(response.content)
        if parsed is None:
            raise AgentInputError("模型返回的结构化结果无效")
        return parsed, {
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.total_tokens,
        }

    def _research_plan_prompt(
        self, run: AgentRun, evidence: list[dict[str, Any]], opportunity: dict[str, Any] | None
    ) -> str:
        return (
            "根据工作区证据生成可证伪、可执行、字段完整的中文研究计划。除论文标题和证据原文外，"
            "标题、研究问题、假设、数据集说明、基线说明、指标、步骤、结果标准、风险与资源约束"
            "全部使用简体中文。所有关键设计必须引用 evidence_id。不得留空；证据不足时应写明"
            "“暂定方案”和选择条件，而不是返回空数组或空字符串。"
            "返回 JSON 字段：title（简洁陈述式中文标题，不能写成问句）, research_question, hypothesis, "
            "scope_and_assumptions, datasets(string[]), "
            "baselines(string[]), metrics(string[]), validation_steps(string[]), expected_supporting_result, "
            "falsification_criteria, risks(string[]), resource_constraints, evidence_refs(string[])。"
            "datasets 至少 2 项、baselines 至少 2 项、metrics 至少 3 项、validation_steps 至少 4 项；"
            "expected_supporting_result 必须给出可观测判据，falsification_criteria 必须明确何时拒绝假设。\n\n"
            f"用户任务：{run.input_payload.get('prompt')}\n"
            f"补充约束：{run.input_payload.get('resource_constraints', '')}\n"
            f"待完善研究计划：{json.dumps((run.context_snapshot or {}).get('research_plan'), ensure_ascii=False)}\n"
            f"已确认机会：{json.dumps(opportunity, ensure_ascii=False) if opportunity else '无'}\n"
            f"证据：{json.dumps(evidence, ensure_ascii=False)}"
        )

    @staticmethod
    def _deep_research_prompt(
        run: AgentRun,
        plan_snapshot: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> str:
        return (
            "你是严谨的深度研究 Agent。请基于冻结的研究计划和给定证据生成中文研究报告，"
            "不得把尚未核验的推断写成事实，不得发明论文、数据或实验结果。必须同时寻找支持线索、"
            "限制条件和可能反驳假设的证据，并用 evidence_id 引用。报告不能停留在文献概述，"
            "必须进一步提出一套可实现、可消融、可证伪的候选研究方法。方法和公式属于待验证设计，"
            "不得表述成已经获得的实验结论。返回 JSON 字段："
            "title, executive_summary, research_landscape, supporting_findings(string[]), "
            "counter_findings(string[]), unresolved_questions(string[]), refined_hypothesis, "
            "recommended_methodology(string[]), proposed_method(object), experimental_design(object), "
            "experiment_plan(string[]), novelty_assessment, risk_register(string[]), "
            "next_actions(string[]), evidence_refs(string[])。proposed_method 必须包含 "
            "name_zh, core_idea, modules(string[]), "
            "objective_function({latex, explanation, symbols}), "
            "formulas([{name, latex, explanation, symbols}]), algorithm_steps(string[]), "
            "implementation_details(string[])；至少给出 2 个与该课题直接相关的公式，并解释符号、"
            "优化目标和它们在实现中的位置。explanation 和 symbols 中出现变量时必须使用行内 LaTeX，"
            "例如 $z_i$、$z_j$、$e_{ij}$，不得把下标写成普通文本。experimental_design 必须包含 datasets(string[]), "
            "baselines(string[]), metrics(string[]), ablations(string[]), statistical_tests(string[]), "
            "expected_supporting_results(string[]), falsification_criteria(string[])。"
            "数据集、基线和指标应尽可能具体；如果证据不足，应标记为“建议/暂定”并说明选择依据。"
            "title 必须是简洁陈述式中文标题，所有叙述字段使用中文。\n\n"
            f"用户补充目标：{run.input_payload.get('prompt')}\n"
            f"冻结研究计划：{json.dumps(plan_snapshot, ensure_ascii=False)}\n"
            f"可用证据：{json.dumps(evidence, ensure_ascii=False)}"
        )

    @staticmethod
    def _code_prompt(run: AgentRun, plan: ResearchPlan, evidence: list[dict[str, Any]]) -> str:
        plan_payload = {
            "title": plan.title,
            "research_question": plan.research_question,
            "hypothesis": plan.hypothesis,
            "datasets": plan.datasets,
            "baselines": plan.baselines,
            "metrics": plan.metrics,
            "validation_steps": plan.validation_steps,
            "constraints": plan.resource_constraints,
        }
        return (
            "生成一个最小、可复现、便于审查的 Python 实验项目。不要包含密钥，不要访问用户本机路径，"
            "不要返回二进制内容。返回 JSON：summary 和 files；files 每项包含 path, language, content。"
            "必须包含 README.md、requirements.txt、配置、训练或评估入口和至少一个测试。\n\n"
            f"用户要求：{run.input_payload.get('prompt')}\n"
            f"偏好框架：{run.input_payload.get('framework', 'PyTorch')}\n"
            f"研究计划：{json.dumps(plan_payload, ensure_ascii=False)}\n"
            f"论文证据：{json.dumps(evidence, ensure_ascii=False)}"
        )

    def _normalize_plan(
        self, data: dict[str, Any], run: AgentRun, opportunity: dict[str, Any] | None
    ) -> dict[str, Any]:
        research_question = str(data.get("research_question") or "").strip()
        hypothesis = str(data.get("hypothesis") or "").strip()
        if not research_question or not hypothesis:
            raise AgentInputError("研究计划缺少研究问题或核心假设")
        title = str(data.get("title") or (opportunity or {}).get("title") or "").strip()
        if not title:
            title = research_question.rstrip("？?")[:120] or "未命名研究计划"
        datasets = self._fill_minimum(
            self._string_list(data.get("datasets")),
            [
                "暂定选择一个领域常用公开基准数据集，并说明纳入依据",
                "暂定选择一个分布或数据类型不同的公开数据集检验外推性",
            ],
            2,
        )
        baselines = self._fill_minimum(
            self._string_list(data.get("baselines")),
            ["当前最强相似工作", "移除候选核心机制的消融基线"],
            2,
        )
        metrics = self._fill_minimum(
            self._string_list(data.get("metrics")),
            ["目标问题核心指标", "有效性或任务性能", "计算与存储开销"],
            3,
        )
        validation_steps = self._fill_minimum(
            self._string_list(data.get("validation_steps")),
            [
                "确定数据集、任务与统一的数据划分",
                "复现最强基线并统一训练预算",
                "实现候选方法并开展组件消融",
                "使用多随机种子和统计检验报告结果",
            ],
            4,
        )
        return {
            "opportunity_id": opportunity.get("opportunity_id") if opportunity else None,
            "opportunity_version_id": opportunity.get("opportunity_version_id")
            if opportunity
            else None,
            "title": title,
            "research_question": research_question,
            "hypothesis": hypothesis,
            "scope_and_assumptions": str(
                data.get("scope_and_assumptions")
                or "暂定在公开数据集与可复现模型上验证；具体数据类型和任务边界需结合证据进一步收缩。"
            ),
            "datasets": datasets,
            "baselines": baselines,
            "metrics": metrics,
            "validation_steps": validation_steps,
            "expected_supporting_result": str(
                data.get("expected_supporting_result")
                or "候选方法在多个数据集和随机种子上稳定改善核心指标，且不会造成不可接受的性能或开销退化。"
            ),
            "falsification_criteria": str(
                data.get("falsification_criteria")
                or "若核心指标提升不显著、无法跨数据集复现，或代价明显高于收益，则拒绝或收缩该假设。"
            ),
            "risks": self._string_list(data.get("risks"))
            or ["当前证据可能不足以覆盖全部相似工作与边界条件。"],
            "resource_constraints": str(
                data.get("resource_constraints")
                or run.input_payload.get("resource_constraints")
                or ""
            ),
            "evidence_refs": self._string_list(data.get("evidence_refs")),
        }

    def _normalize_deep_research(
        self,
        data: dict[str, Any],
        plan_snapshot: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        executive_summary = str(data.get("executive_summary") or "").strip()
        refined_hypothesis = str(data.get("refined_hypothesis") or "").strip()
        if not executive_summary or not refined_hypothesis:
            raise AgentInputError("深度研究报告缺少核心结论或精炼假设")
        allowed_refs = {str(item.get("evidence_id")) for item in evidence}
        evidence_refs = [
            item for item in self._string_list(data.get("evidence_refs")) if item in allowed_refs
        ]
        if not evidence_refs:
            raise AgentInputError("深度研究报告没有引用任何可验证证据")
        title = str(data.get("title") or plan_snapshot.get("title") or "深度研究报告").strip()
        raw_method = data.get("proposed_method")
        if not isinstance(raw_method, dict):
            raw_method = {}
        raw_formulas = raw_method.get("formulas")
        formulas: list[dict[str, str]] = []
        if isinstance(raw_formulas, list):
            for raw_formula in raw_formulas[:8]:
                if not isinstance(raw_formula, dict):
                    continue
                latex = str(raw_formula.get("latex") or "").strip()
                explanation = str(raw_formula.get("explanation") or "").strip()
                if not latex or not explanation:
                    continue
                formulas.append(
                    {
                        "name": str(raw_formula.get("name") or "候选公式").strip(),
                        "latex": latex,
                        "explanation": explanation,
                        "symbols": str(raw_formula.get("symbols") or "").strip(),
                    }
                )
        if len(formulas) < 2:
            raise AgentInputError("深度研究报告至少需要两个可审查的候选公式")
        raw_objective = raw_method.get("objective_function")
        if isinstance(raw_objective, dict):
            objective_function = {
                "latex": str(raw_objective.get("latex") or "").strip(),
                "explanation": str(raw_objective.get("explanation") or "").strip(),
                "symbols": str(raw_objective.get("symbols") or "").strip(),
            }
        else:
            objective_function = {
                "latex": "",
                "explanation": str(raw_objective or "").strip(),
                "symbols": "",
            }
        proposed_method = {
            "name_zh": str(raw_method.get("name_zh") or "待验证候选方法").strip(),
            "core_idea": str(
                raw_method.get("core_idea")
                or "根据证据提出可消融的候选机制，并通过对照实验验证其必要性与适用边界。"
            ).strip(),
            "modules": self._string_list(raw_method.get("modules")),
            "objective_function": objective_function,
            "formulas": formulas,
            "algorithm_steps": self._string_list(raw_method.get("algorithm_steps")),
            "implementation_details": self._string_list(raw_method.get("implementation_details")),
        }
        raw_design = data.get("experimental_design")
        if not isinstance(raw_design, dict):
            raw_design = {}
        experimental_design = {
            "datasets": self._fill_minimum(
                self._string_list(raw_design.get("datasets")),
                self._string_list(plan_snapshot.get("datasets")),
                2,
            ),
            "baselines": self._fill_minimum(
                self._string_list(raw_design.get("baselines")),
                self._string_list(plan_snapshot.get("baselines")),
                2,
            ),
            "metrics": self._fill_minimum(
                self._string_list(raw_design.get("metrics")),
                self._string_list(plan_snapshot.get("metrics")),
                3,
            ),
            "ablations": self._string_list(raw_design.get("ablations"))
            or ["移除候选核心机制", "改变关键权衡系数并观察性能—代价曲线"],
            "statistical_tests": self._string_list(raw_design.get("statistical_tests"))
            or [
                "至少 5 个随机种子，报告均值、标准差和 95% 置信区间",
                "采用配对显著性检验并报告效应量",
            ],
            "expected_supporting_results": self._string_list(
                raw_design.get("expected_supporting_results")
            ),
            "falsification_criteria": self._string_list(raw_design.get("falsification_criteria"))
            or [
                str(
                    plan_snapshot.get("falsification_criteria")
                    or "核心指标未稳定改善或代价超过收益时拒绝假设"
                )
            ],
        }
        return {
            "research_plan_id": plan_snapshot.get("research_plan_id"),
            "opportunity_version_id": plan_snapshot.get("opportunity_version_id"),
            "title": title,
            "executive_summary": executive_summary,
            "research_landscape": str(data.get("research_landscape") or "").strip(),
            "supporting_findings": self._string_list(data.get("supporting_findings")),
            "counter_findings": self._string_list(data.get("counter_findings")),
            "unresolved_questions": self._string_list(data.get("unresolved_questions")),
            "refined_hypothesis": refined_hypothesis,
            "recommended_methodology": self._string_list(data.get("recommended_methodology")),
            "proposed_method": proposed_method,
            "experimental_design": experimental_design,
            "experiment_plan": self._string_list(data.get("experiment_plan")),
            "novelty_assessment": str(data.get("novelty_assessment") or "").strip(),
            "risk_register": self._string_list(data.get("risk_register")),
            "next_actions": self._string_list(data.get("next_actions")),
            "evidence_refs": evidence_refs,
            "review_status": "pending_review",
        }

    @staticmethod
    def _normalize_files(value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        files: list[dict[str, str]] = []
        total_chars = 0
        for raw in value[: settings.agent_code_max_files]:
            if not isinstance(raw, dict):
                continue
            path = str(raw.get("path") or "").replace("\\", "/").strip("/")
            content = str(raw.get("content") or "")
            pure = PurePosixPath(path)
            if not path or pure.is_absolute() or ".." in pure.parts or not content:
                continue
            if any(part.startswith(".") for part in pure.parts):
                continue
            remaining = settings.agent_code_max_chars - total_chars
            if remaining <= 0:
                break
            content = content[:remaining]
            total_chars += len(content)
            files.append(
                {
                    "path": str(pure),
                    "content": content,
                    "language": str(raw.get("language") or "text"),
                }
            )
        return files

    @staticmethod
    def _plan_markdown(plan: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
        def bullets(values: list[str]) -> str:
            return "\n".join(f"- {value}" for value in values) or "- 暂无"

        sources = "\n".join(
            f"- [{item['evidence_id']}] {item.get('paper_title') or '未命名论文'} / {item.get('section') or '未知章节'}"
            for item in evidence
        )
        return (
            f"# {plan['title']}\n\n> 研究计划草案\n\n## 研究问题\n{plan['research_question']}\n\n"
            f"## 核心假设\n{plan['hypothesis']}\n\n## 范围与前提\n{plan['scope_and_assumptions']}\n\n"
            f"## 数据集\n{bullets(plan['datasets'])}\n\n## Baselines\n{bullets(plan['baselines'])}\n\n"
            f"## 指标\n{bullets(plan['metrics'])}\n\n## 验证步骤\n{bullets(plan['validation_steps'])}\n\n"
            f"## 证伪条件\n{plan['falsification_criteria']}\n\n## 风险\n{bullets(plan['risks'])}\n\n"
            f"## 证据来源\n{sources}\n"
        )

    @staticmethod
    def _deep_research_markdown(report: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
        def bullets(values: list[str]) -> str:
            return "\n".join(f"- {value}" for value in values) or "- 暂无"

        method = report.get("proposed_method") or {}
        design = report.get("experimental_design") or {}
        objective = method.get("objective_function") or {}
        if isinstance(objective, str):
            objective = {"latex": "", "explanation": objective, "symbols": ""}
        objective_parts: list[str] = []
        if objective.get("latex"):
            objective_parts.append(f"$$\n{objective['latex']}\n$$")
        if objective.get("explanation"):
            objective_parts.append(f"**作用与解释：** {objective['explanation']}")
        if objective.get("symbols"):
            objective_parts.append(f"**符号说明：** {objective['symbols']}")
        objective_markdown = "\n\n".join(objective_parts) or "待补充可计算的优化目标。"
        formula_sections: list[str] = []
        for index, formula in enumerate(method.get("formulas") or [], 1):
            name = formula.get("name") or f"候选公式 {index}"
            symbols = formula.get("symbols") or "符号定义待实验设计进一步明确。"
            formula_sections.append(
                f"### {index}. {name}\n\n"
                f"$$\n{formula.get('latex') or ''}\n$$\n\n"
                f"**作用与解释：** {formula.get('explanation') or '待验证。'}\n\n"
                f"**符号说明：** {symbols}"
            )
        formulas = (
            "\n\n".join(formula_sections)
            or "尚未形成可审查的候选公式，需要补充方法设计后再进入实现阶段。"
        )

        by_id = {str(item.get("evidence_id")): item for item in evidence}
        sources = "\n".join(
            f"- [{reference}] {by_id[reference].get('paper_title') or '未命名论文'} / "
            f"{by_id[reference].get('section') or '未知章节'} / "
            f"{by_id[reference].get('relation') or '相关证据'}"
            for reference in report["evidence_refs"]
            if reference in by_id
        )
        return (
            f"# {report['title']}\n\n> 深度研究报告草案，等待人工确认。\n\n"
            f"## 核心结论\n{report['executive_summary']}\n\n"
            f"## 研究版图\n{report['research_landscape']}\n\n"
            f"## 支持性发现\n{bullets(report['supporting_findings'])}\n\n"
            f"## 反证与限制条件\n{bullets(report['counter_findings'])}\n\n"
            f"## 尚未解决的问题\n{bullets(report['unresolved_questions'])}\n\n"
            f"## 精炼后的可证伪假设\n{report['refined_hypothesis']}\n\n"
            f"## 推荐方法\n{bullets(report['recommended_methodology'])}\n\n"
            f"## 候选研究方法：{method.get('name_zh') or '待验证候选方法'}\n\n"
            f"### 核心思路\n{method.get('core_idea') or '待补充'}\n\n"
            f"### 方法模块\n{bullets(method.get('modules') or [])}\n\n"
            f"### 优化目标\n{objective_markdown}\n\n"
            f"### 数学定义与候选公式\n{formulas}\n\n"
            f"### 算法步骤\n{bullets(method.get('algorithm_steps') or [])}\n\n"
            f"### 实现要点\n{bullets(method.get('implementation_details') or [])}\n\n"
            f"## 实验设计\n\n### 数据集\n{bullets(design.get('datasets') or [])}\n\n"
            f"### 对比基线\n{bullets(design.get('baselines') or [])}\n\n"
            f"### 评价指标\n{bullets(design.get('metrics') or [])}\n\n"
            f"### 消融实验\n{bullets(design.get('ablations') or [])}\n\n"
            f"### 统计检验\n{bullets(design.get('statistical_tests') or [])}\n\n"
            f"### 支持假设的预期结果\n{bullets(design.get('expected_supporting_results') or [])}\n\n"
            f"### 证伪条件\n{bullets(design.get('falsification_criteria') or [])}\n\n"
            f"## 实验计划\n{bullets(report['experiment_plan'])}\n\n"
            f"## 新颖性判断\n{report['novelty_assessment']}\n\n"
            f"## 风险清单\n{bullets(report['risk_register'])}\n\n"
            f"## 下一步行动\n{bullets(report['next_actions'])}\n\n"
            f"## 引用证据\n{sources or '- 暂无'}\n"
        )

    def _transition(self, run: AgentRun, status: str, stage: str, progress: float) -> None:
        if run.status == "cancelled":
            raise AgentConflictError("Agent 任务已取消")
        run.status = status
        run.current_stage = stage
        run.progress = progress
        if run.task_id:
            task = self.db.get(Task, run.task_id)
            if task and task.status == "queued" and status == "running":
                TaskService(self.db).transition(run.task_id, "running", progress=progress)
            elif task and task.status == "running":
                TaskService(self.db).update_progress(run.task_id, progress)
        self.db.commit()

    def _step(
        self,
        run: AgentRun,
        sequence: int,
        stage: str,
        status: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        step = self.db.scalar(
            select(AgentStep).where(AgentStep.run_id == run.id, AgentStep.sequence == sequence)
        )
        if step is None:
            step = AgentStep(run_id=run.id, sequence=sequence, stage=stage)
            self.db.add(step)
        step.stage = stage
        step.status = status
        step.summary = summary
        step.details = details or {}
        self.db.commit()

    def _fail(self, run: AgentRun, error: str) -> None:
        run.status = "failed"
        run.current_stage = "failed"
        run.error = error[:2000]
        if run.task_id:
            task = self.db.get(Task, run.task_id)
            if task and task.status in {"queued", "running", "waiting_for_user"}:
                if task.status == "queued":
                    TaskService(self.db).transition(run.task_id, "running", progress=run.progress)
                TaskService(self.db).transition(
                    run.task_id, "failed", progress=run.progress, error=run.error
                )
        self._finish_assistant(run, f"Agent 执行失败：{run.error}", failed=True)
        self.db.commit()

    def _finish_assistant(self, run: AgentRun, content: str, *, failed: bool) -> None:
        message = (
            self.db.get(ChatMessage, run.assistant_message_id) if run.assistant_message_id else None
        )
        if message:
            message.content = content
            message.status = "failed" if failed else "completed"
            message.error_message = run.error if failed else None
            message.grounding_status = "grounded" if not failed else "retrieval_failed"
        conversation = (
            self.db.get(ChatConversation, run.conversation_id) if run.conversation_id else None
        )
        if conversation:
            conversation.last_message_at = datetime.now(timezone.utc)

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any] | None:
        try:
            value = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", content)
            if not match:
                return None
            try:
                value = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _fill_minimum(values: list[str], fallbacks: list[str], minimum: int) -> list[str]:
        result: list[str] = []
        for value in [*values, *fallbacks]:
            normalized = str(value).strip()
            if normalized and normalized not in result:
                result.append(normalized)
            if len(result) >= minimum:
                break
        while len(result) < minimum:
            result.append(f"暂定设计项 {len(result) + 1}（待补充证据后细化）")
        return result

    @staticmethod
    def _mime_type(filename: str) -> str:
        if filename.endswith(".md"):
            return "text/markdown"
        if filename.endswith(".json"):
            return "application/json"
        if filename.endswith((".yaml", ".yml")):
            return "application/yaml"
        if filename.endswith(".py"):
            return "text/x-python"
        return "text/plain"

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        text = f"{type(exc).__name__}: {exc}"
        text = re.sub(r"(?i)sk-[a-z0-9_-]+", "[redacted]", text)
        return text[:2000]
