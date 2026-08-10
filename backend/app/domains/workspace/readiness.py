"""Workspace research readiness aggregation (W0).

Single source of truth for "can I run Discover / why not / where to go next".

Five dimensions - corpus, retrieval, knowledge, discover, research - each
report ``ready`` / ``waiting`` / ``blocked`` plus human-explainable blocking
actions that point at the page which unblocks them. The overview progress bar
is driven entirely by this endpoint; every count here is a real
``func.count()`` (not a paginated frontend total) so the numbers agree across
pages.

Design notes:
- Dimension states: ``ready`` (usable), ``waiting`` (prerequisites exist but a
  background pipeline task is still running - not a user blocking action),
  ``blocked`` (user must act; blocking_actions explains what and where).
- ``recommended_next_action`` is the first non-ready dimension's first
  blocking action - the single "what to do next" the overview page shows.
- Milvus chunk count is best-effort: a Milvus outage degrades to ``None``
  instead of failing the whole readiness endpoint (W5 degradation spirit).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.domains.discover.models import DiscoverRun, ResearchOpportunity, ResearchPlan
from app.domains.knowledge.models import KnowledgeItem
from app.domains.paper.models import Paper
from app.domains.task.models import Task
from app.domains.workspace.models import Workspace

# Status semantics kept in sync with discover/service.py + task domain.
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "cancelled"}
WAITING_RUN_STATUSES = {"waiting_for_user", "waiting_for_fulltext"}
PIPELINE_PENDING_STATUSES = {"queued", "running", "waiting_for_user"}
CLOSED_OPPORTUNITY_STATUSES = {"confirmed", "edited_confirmed", "rejected"}
CONFIRMED_OPPORTUNITY_STATUSES = {"confirmed", "edited_confirmed"}
# Background pipeline tasks that signal "the system is still working".
PIPELINE_TASK_TYPES = ("parse_pdf", "extract_knowledge", "embed_chunks")
# Knowledge states that are produced by extraction but not yet human-confirmed.
KNOWLEDGE_PENDING_STATUSES = ("extracted_candidate", "evidence_backed_proposal")


class WorkspaceReadinessService:
    """Aggregate per-workspace research readiness into one explainable object."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------ entry
    def get_readiness(self, workspace: Workspace) -> dict[str, Any]:
        """Return the full readiness document for a workspace."""
        counts = self._counts(workspace.id)
        profile_set = self._profile_set(workspace)
        dimensions = [
            self._corpus(counts, workspace.id),
            self._retrieval(counts, workspace.id),
            self._knowledge(counts, workspace.id),
            self._discover(counts, workspace, profile_set),
            self._research(counts, workspace.id),
        ]
        return {
            "workspace_id": workspace.id,
            "counts": counts,
            "dimensions": dimensions,
            "recommended_next_action": self._recommended(dimensions, counts, workspace.id),
        }

    # ----------------------------------------------------------------- counts
    def _counts(self, workspace_id: str) -> dict[str, int]:
        def count(q: Any) -> int:
            return int(self.db.execute(q).scalar() or 0)

        papers_q = Paper.workspace_id == workspace_id
        return {
            "papers": count(
                select(func.count()).select_from(Paper).where(papers_q, Paper.is_deleted.is_(False))
            ),
            "papers_with_pdf": count(
                select(func.count())
                .select_from(Paper)
                .where(papers_q, Paper.is_deleted.is_(False), Paper.primary_artifact_id.is_not(None))
            ),
            "parsed_papers": count(
                select(func.count())
                .select_from(Paper)
                .where(papers_q, Paper.is_deleted.is_(False), Paper.parse_status == "parsed")
            ),
            "extracted_papers": count(
                select(func.count())
                .select_from(Paper)
                .where(papers_q, Paper.is_deleted.is_(False), Paper.extract_status == "extracted")
            ),
            "knowledge_items": count(
                select(func.count())
                .select_from(KnowledgeItem)
                .where(KnowledgeItem.workspace_id == workspace_id, KnowledgeItem.is_deleted.is_(False))
            ),
            "confirmed_items": count(
                select(func.count())
                .select_from(KnowledgeItem)
                .where(
                    KnowledgeItem.workspace_id == workspace_id,
                    KnowledgeItem.is_deleted.is_(False),
                    KnowledgeItem.status == "human_confirmed",
                )
            ),
            "pending_knowledge": count(
                select(func.count())
                .select_from(KnowledgeItem)
                .where(
                    KnowledgeItem.workspace_id == workspace_id,
                    KnowledgeItem.is_deleted.is_(False),
                    KnowledgeItem.status.in_(KNOWLEDGE_PENDING_STATUSES),
                )
            ),
            "runs": count(
                select(func.count())
                .select_from(DiscoverRun)
                .where(DiscoverRun.workspace_id == workspace_id, DiscoverRun.deleted_at.is_(None))
            ),
            "pending_runs": count(
                select(func.count())
                .select_from(DiscoverRun)
                .where(
                    DiscoverRun.workspace_id == workspace_id,
                    DiscoverRun.deleted_at.is_(None),
                    or_(
                        DiscoverRun.status.in_(WAITING_RUN_STATUSES),
                        DiscoverRun.status.in_(PIPELINE_PENDING_STATUSES),
                    ),
                )
            ),
            "opportunities": count(
                select(func.count())
                .select_from(ResearchOpportunity)
                .where(
                    ResearchOpportunity.workspace_id == workspace_id,
                    ResearchOpportunity.is_deleted.is_(False),
                )
            ),
            "pending_opportunities": count(
                select(func.count())
                .select_from(ResearchOpportunity)
                .where(
                    ResearchOpportunity.workspace_id == workspace_id,
                    ResearchOpportunity.is_deleted.is_(False),
                    ResearchOpportunity.status.not_in(CLOSED_OPPORTUNITY_STATUSES),
                )
            ),
            "confirmed_opportunities": count(
                select(func.count())
                .select_from(ResearchOpportunity)
                .where(
                    ResearchOpportunity.workspace_id == workspace_id,
                    ResearchOpportunity.is_deleted.is_(False),
                    ResearchOpportunity.status.in_(CONFIRMED_OPPORTUNITY_STATUSES),
                )
            ),
            "research_plans": count(
                select(func.count()).select_from(ResearchPlan).where(ResearchPlan.workspace_id == workspace_id)
            ),
            "active_tasks": count(
                select(func.count())
                .select_from(Task)
                .where(
                    Task.workspace_id == workspace_id,
                    Task.is_deleted.is_(False),
                    Task.task_type.in_(PIPELINE_TASK_TYPES),
                    Task.status.in_(PIPELINE_PENDING_STATUSES),
                )
            ),
        }

    def _indexed_chunks(self, workspace_id: str) -> int | None:
        """Best-effort Milvus chunk count; degrade to None on outage."""
        try:
            from app.domains.retrieval.milvus_client import MilvusClient

            return MilvusClient().count_by_workspace(workspace_id)
        except Exception:
            return None

    @staticmethod
    def _profile_set(workspace: Workspace) -> bool:
        return bool(
            (workspace.topic or "").strip()
            or (workspace.goals or "").strip()
            or any(q.strip() for q in workspace.active_questions)
        )

    # ------------------------------------------------------------- dimensions
    def _corpus(self, c: dict[str, int], workspace_id: str) -> dict[str, Any]:
        ready = c["parsed_papers"] >= 1
        waiting = (not ready) and c["papers"] > 0 and c["active_tasks"] > 0
        blocking: list[dict[str, str]] = []
        if c["papers"] == 0:
            blocking.append(self._action("添加论文", "还没有任何论文作为证据基础。", f"/workspaces/{workspace_id}/papers"))
        elif not ready and not waiting:
            blocking.append(self._action("等待或重试 PDF 解析", "已有论文但尚未完成解析。", f"/workspaces/{workspace_id}/activity"))
        return self._dimension(
            "corpus", "文献", ready, waiting,
            f"{c['papers']} 篇论文 · {c['parsed_papers']} 篇已解析",
            blocking,
        )

    def _retrieval(self, c: dict[str, int], workspace_id: str) -> dict[str, Any]:
        ready = c["extracted_papers"] >= 1
        waiting = (not ready) and c["parsed_papers"] > 0 and c["active_tasks"] > 0
        blocking: list[dict[str, str]] = []
        if c["parsed_papers"] == 0 and c["papers"] > 0:
            blocking.append(self._action("等待论文解析", "解析完成后才能抽取知识与建立索引。", f"/workspaces/{workspace_id}/activity"))
        elif not ready and not waiting:
            blocking.append(self._action("运行知识抽取与索引", "没有可用于检索的抽取结果。", f"/workspaces/{workspace_id}/activity"))
        chunks = self._indexed_chunks(workspace_id)
        chunk_text = f" · {chunks} chunks" if chunks is not None else ""
        return self._dimension(
            "retrieval", "检索", ready, waiting,
            f"{c['extracted_papers']} 篇已抽取{chunk_text}",
            blocking,
        )

    def _knowledge(self, c: dict[str, int], workspace_id: str) -> dict[str, Any]:
        ready = c["knowledge_items"] >= 1
        waiting = (not ready) and c["extracted_papers"] > 0 and c["active_tasks"] > 0
        blocking: list[dict[str, str]] = []
        if not ready and not waiting:
            blocking.append(self._action("等待知识抽取", "当前还没有可用的知识条目。", f"/workspaces/{workspace_id}/activity"))
        return self._dimension(
            "knowledge", "知识", ready, waiting,
            f"{c['knowledge_items']} 条知识 · {c['confirmed_items']} 条已确认",
            blocking,
        )

    def _discover(self, c: dict[str, int], workspace: Workspace, profile_set: bool) -> dict[str, Any]:
        retrieval_ready = c["extracted_papers"] >= 1
        knowledge_ready = c["knowledge_items"] >= 1
        ready = profile_set and retrieval_ready and knowledge_ready
        waiting = (not ready) and c["pending_runs"] > 0
        workspace_id = workspace.id
        blocking: list[dict[str, str]] = []
        if not profile_set:
            blocking.append(self._action("设置研究主题与问题", "Discover 需要研究主题、目标或研究问题。", f"/workspaces/{workspace_id}/settings"))
        if not retrieval_ready:
            blocking.append(self._action("等待检索就绪", "先完成论文抽取与索引才能检索。", f"/workspaces/{workspace_id}/activity"))
        if not knowledge_ready:
            blocking.append(self._action("等待知识就绪", "先抽取知识才能作为发现输入。", f"/workspaces/{workspace_id}/activity"))
        return self._dimension(
            "discover", "发现", ready, waiting,
            f"{c['runs']} 次运行 · {c['pending_runs']} 项待处理",
            blocking,
        )

    def _research(self, c: dict[str, int], workspace_id: str) -> dict[str, Any]:
        ready = c["confirmed_opportunities"] >= 1 or c["research_plans"] >= 1
        blocking: list[dict[str, str]] = []
        if not ready:
            if c["pending_opportunities"] > 0:
                blocking.append(self._action("处理待确认机会", "有人工待确认的研究机会。", f"/workspaces/{workspace_id}/discover"))
            else:
                blocking.append(self._action("运行 Discover 并确认机会", "先产生候选，再人工确认一个研究方向。", f"/workspaces/{workspace_id}/discover"))
        return self._dimension(
            "research", "研究", ready, False,
            f"{c['confirmed_opportunities']} 个已确认机会 · {c['research_plans']} 个研究计划",
            blocking,
        )

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _dimension(
        key: str,
        label: str,
        ready: bool,
        waiting: bool,
        summary: str,
        blocking_actions: list[dict[str, str]],
    ) -> dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "ready": ready,
            "waiting": waiting,
            "summary": summary,
            "blocking_actions": blocking_actions,
        }

    @staticmethod
    def _action(action: str, reason: str, href: str) -> dict[str, str]:
        return {"action": action, "reason": reason, "href": href}

    def _recommended(
        self,
        dimensions: list[dict[str, Any]],
        counts: dict[str, int],
        workspace_id: str,
    ) -> dict[str, str]:
        """First blocked capability dimension's first action - the next step.

        The ``research`` dimension is intentionally excluded from this loop:
        "no confirmed result yet" does not block the loop - it is simply the
        loop's next step, surfaced after the capability dimensions are ready.
        """
        for dim in dimensions:
            if dim["key"] == "research":
                continue
            if dim["ready"]:
                continue
            if dim["waiting"]:
                return {
                    "title": "查看处理进度",
                    "description": f"{dim['label']}：{dim['summary']}，后台任务还在运行。",
                    "href": f"/workspaces/{workspace_id}/activity",
                    "label": "打开处理中心",
                }
            if dim["blocking_actions"]:
                first = dim["blocking_actions"][0]
                return {
                    "title": first["action"],
                    "description": first["reason"],
                    "href": first["href"],
                    "label": first["action"],
                }
        # Capability dimensions are ready - keep the HITL loop moving.
        if counts["pending_knowledge"] > 0 and counts["confirmed_items"] == 0:
            return {
                "title": "审核确认知识",
                "description": f"已有 {counts['pending_knowledge']} 条待审核知识，确认后可作为更可信的发现输入。",
                "href": f"/workspaces/{workspace_id}/knowledge",
                "label": "打开知识工作台",
            }
        if counts["pending_opportunities"] > 0:
            return {
                "title": "处理待确认机会",
                "description": "各维度已就绪，先处理待人工确认的研究机会。",
                "href": f"/workspaces/{workspace_id}/discover",
                "label": "查看机会",
            }
        if counts["confirmed_opportunities"] == 0 and counts["research_plans"] == 0:
            return {
                "title": "运行 Discover 并确认机会",
                "description": "研究准备度已就绪，运行发现流程产生候选，再人工确认一个研究方向。",
                "href": f"/workspaces/{workspace_id}/discover",
                "label": "启动 Discover",
            }
        return {
            "title": "进入研究中心",
            "description": "研究准备度全部就绪，继续推进研究计划与代码生成。",
            "href": f"/workspaces/{workspace_id}/plans",
            "label": "打开研究中心",
        }
