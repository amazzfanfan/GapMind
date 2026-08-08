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
        if agent_type not in {"research_plan", "code_generation"}:
            raise AgentInputError("不支持的 Agent 类型")
        payload = dict(input_payload or {})
        payload["prompt"] = prompt.strip()
        if not payload["prompt"]:
            raise AgentInputError("任务描述不能为空")
        if agent_type == "code_generation":
            plan_id = str(payload.get("research_plan_id") or "")
            plan = self.db.get(ResearchPlan, plan_id) if plan_id else None
            if plan is None or plan.workspace_id != workspace_id:
                raise AgentInputError("代码生成必须选择当前工作区中的研究计划")

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
