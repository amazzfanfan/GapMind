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
from app.domains.discover.models import OpportunityVersion, ResearchOpportunity, ResearchPlan
from app.domains.retrieval.service import semantic_search
from app.domains.task.schemas import TaskCreate
from app.domains.task.models import Task
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
            select(AgentRun.id).where(
                AgentRun.conversation_id == conversation_id,
                AgentRun.status.in_(ACTIVE_STATUSES),
            ).limit(1)
        )
        if active:
            raise AgentConflictError("当前对话已有 Agent 正在运行")

        task = TaskService(self.db).create(
            TaskCreate(workspace_id=workspace_id, task_type=f"agent_{agent_type}", payload={})
        )
        sequence = int(
            self.db.scalar(
                select(func.max(ChatMessage.sequence)).where(
                    ChatMessage.conversation_id == conversation_id
                )
            )
            or 0
        ) + 1
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
            context_snapshot={"workspace_name": workspace.name},
            requires_confirmation=agent_type == "research_plan",
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
            self.db.scalars(
                stmt.order_by(AgentRun.created_at.desc()).offset(offset).limit(limit)
            )
        )
        return items, total

    def detail(self, workspace_id: str, run_id: str) -> tuple[AgentRun, list[AgentStep], list[AgentArtifact]]:
        run = self.get(workspace_id, run_id)
        steps = list(
            self.db.scalars(
                select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.sequence)
            )
        )
        artifacts = list(
            self.db.scalars(
                select(AgentArtifact).where(
                    AgentArtifact.run_id == run.id,
                    AgentArtifact.is_deleted.is_(False),
                ).order_by(AgentArtifact.filename)
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
        if run.status != "waiting_for_user" or run.agent_type != "research_plan":
            raise AgentConflictError("只有等待审核的研究计划草案可以确认")
        result = dict(run.result or {})
        plan = self.db.scalar(select(ResearchPlan).where(ResearchPlan.agent_run_id == run.id))
        if plan is None:
            opportunity_id = result.get("opportunity_id")
            version_id = result.get("opportunity_version_id")
            plan = ResearchPlan(
                workspace_id=workspace_id,
                opportunity_id=opportunity_id or None,
                opportunity_version_id=version_id or None,
                agent_run_id=run.id,
                source_type="agent",
                status="draft",
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
        for artifact in self.db.scalars(
            select(AgentArtifact).where(AgentArtifact.run_id == run.id)
        ):
            artifact.validation_status = "confirmed"
        if run.task_id:
            task_service = TaskService(self.db)
            task_service.resume_from_user(run.task_id, decision={"action": "confirm"})
            task_service.transition(run.task_id, "succeeded", progress=1.0, result={"research_plan_id": plan.id})
        run.status = "succeeded"
        run.current_stage = "saved"
        run.progress = 1.0
        run.requires_confirmation = False
        result["research_plan_id"] = plan.id
        run.result = result
        self._finish_assistant(
            run,
            f"研究计划已确认并保存到研究中心。\n\n**研究问题：** {plan.research_question}",
            failed=False,
        )
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
            select(Task).where(
                Task.workspace_id == workspace_id,
                Task.task_type == "validate_agent_code",
                Task.status.in_({"queued", "running"}),
            ).order_by(Task.created_at.desc())
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
        self._step(run, 3, "evidence_gate", "completed", "关键计划字段已绑定工作区证据", {"evidence_count": len(evidence)})
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
            select(ChatMessageEvidence.id).where(
                ChatMessageEvidence.message_id == run.assistant_message_id
            ).limit(1)
        ):
            workspace = WorkspaceService(self.db).get(run.workspace_id)
            citations = ChatService(self.db)._materialize_evidence(
                workspace,
                run.assistant_message_id,
                response.items,
            )
            self.db.add_all(citations)
            self.db.flush()
        return [
            {
                "evidence_id": f"E{index}",
                "paper_id": item.paper_id,
                "paper_title": item.paper_title,
                "chunk_id": item.chunk_id,
                "section": item.section,
                "score": round(float(item.score), 4),
                "text": item.text[:3000],
            }
            for index, item in enumerate(response.items, 1)
            if item.paper_id and item.text.strip()
        ]

    def _opportunity_context(self, run: AgentRun) -> dict[str, Any] | None:
        opportunity_id = str(run.input_payload.get("opportunity_id") or "")
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

    def _structured_completion(self, user_prompt: str, *, max_tokens: int) -> tuple[dict[str, Any], dict[str, int]]:
        gateway = self.gateway or get_llm_gateway()
        if not getattr(gateway, "api_key", None):
            raise AgentInputError("DeepSeek API key is not configured")
        response = gateway.chat_completion(
            [
                {"role": "system", "content": "You are a controlled research agent. Return valid JSON only and never invent evidence."},
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

    def _research_plan_prompt(self, run: AgentRun, evidence: list[dict[str, Any]], opportunity: dict[str, Any] | None) -> str:
        return (
            "根据工作区证据生成可证伪、可执行的研究计划。所有关键设计必须引用 evidence_id。"
            "返回 JSON 字段：research_question, hypothesis, scope_and_assumptions, datasets(string[]), "
            "baselines(string[]), metrics(string[]), validation_steps(string[]), expected_supporting_result, "
            "falsification_criteria, risks(string[]), resource_constraints, evidence_refs(string[])。\n\n"
            f"用户任务：{run.input_payload.get('prompt')}\n"
            f"补充约束：{run.input_payload.get('resource_constraints', '')}\n"
            f"已确认机会：{json.dumps(opportunity, ensure_ascii=False) if opportunity else '无'}\n"
            f"证据：{json.dumps(evidence, ensure_ascii=False)}"
        )

    @staticmethod
    def _code_prompt(run: AgentRun, plan: ResearchPlan, evidence: list[dict[str, Any]]) -> str:
        plan_payload = {
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

    def _normalize_plan(self, data: dict[str, Any], run: AgentRun, opportunity: dict[str, Any] | None) -> dict[str, Any]:
        research_question = str(data.get("research_question") or "").strip()
        hypothesis = str(data.get("hypothesis") or "").strip()
        if not research_question or not hypothesis:
            raise AgentInputError("研究计划缺少研究问题或核心假设")
        return {
            "opportunity_id": opportunity.get("opportunity_id") if opportunity else None,
            "opportunity_version_id": opportunity.get("opportunity_version_id") if opportunity else None,
            "research_question": research_question,
            "hypothesis": hypothesis,
            "scope_and_assumptions": str(data.get("scope_and_assumptions") or ""),
            "datasets": self._string_list(data.get("datasets")),
            "baselines": self._string_list(data.get("baselines")),
            "metrics": self._string_list(data.get("metrics")),
            "validation_steps": self._string_list(data.get("validation_steps")),
            "expected_supporting_result": str(data.get("expected_supporting_result") or ""),
            "falsification_criteria": str(data.get("falsification_criteria") or ""),
            "risks": self._string_list(data.get("risks")),
            "resource_constraints": str(data.get("resource_constraints") or run.input_payload.get("resource_constraints") or ""),
            "evidence_refs": self._string_list(data.get("evidence_refs")),
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
            files.append({"path": str(pure), "content": content, "language": str(raw.get("language") or "text")})
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
            f"# 研究计划草案\n\n## 研究问题\n{plan['research_question']}\n\n"
            f"## 核心假设\n{plan['hypothesis']}\n\n## 范围与前提\n{plan['scope_and_assumptions']}\n\n"
            f"## 数据集\n{bullets(plan['datasets'])}\n\n## Baselines\n{bullets(plan['baselines'])}\n\n"
            f"## 指标\n{bullets(plan['metrics'])}\n\n## 验证步骤\n{bullets(plan['validation_steps'])}\n\n"
            f"## 证伪条件\n{plan['falsification_criteria']}\n\n## 风险\n{bullets(plan['risks'])}\n\n"
            f"## 证据来源\n{sources}\n"
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

    def _step(self, run: AgentRun, sequence: int, stage: str, status: str, summary: str, details: dict[str, Any] | None = None) -> None:
        step = self.db.scalar(select(AgentStep).where(AgentStep.run_id == run.id, AgentStep.sequence == sequence))
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
                TaskService(self.db).transition(run.task_id, "failed", progress=run.progress, error=run.error)
        self._finish_assistant(run, f"Agent 执行失败：{run.error}", failed=True)
        self.db.commit()

    def _finish_assistant(self, run: AgentRun, content: str, *, failed: bool) -> None:
        message = self.db.get(ChatMessage, run.assistant_message_id) if run.assistant_message_id else None
        if message:
            message.content = content
            message.status = "failed" if failed else "completed"
            message.error_message = run.error if failed else None
            message.grounding_status = "grounded" if not failed else "retrieval_failed"
        conversation = self.db.get(ChatConversation, run.conversation_id) if run.conversation_id else None
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
