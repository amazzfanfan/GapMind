"""ExternalRetrievalService: Semantic Scholar external novelty search + OA import.

Carved out of the monolithic DiscoverService (MA-1 maintenance refactor).
Owns everything that talks to the outside world for the external-novelty
stage: query construction, S2 relevance/exact lookups, role judgement, OA PDF
import, and the full-text pipeline state machine that resumes a run once an
imported paper is ready.

It holds a ``service`` back-reference (the DiscoverService facade) so shared
helpers like ``_cancelled`` / ``_claim_text`` / ``_parse_json`` stay in one
place instead of being duplicated.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.artifact.models import Artifact
from app.domains.artifact.service import ArtifactService
from app.domains.discover.models import DiscoverExternalCandidate, DiscoverRun
from app.domains.discover.ports import ExternalSearchPort
from app.domains.discover.schemas import DiscoverConfig, DiscoverScope
from app.domains.discover.utils import accumulate_tokens, parse_json
from app.domains.knowledge.models import EvidenceSpan, KnowledgeItem
from app.domains.paper.models import Paper
from app.domains.paper.schemas import PaperCreate
from app.domains.paper.service import PaperService
from app.domains.task.models import Task
from app.domains.task.service import TaskService
from app.gateway.llm import LLMGateway
from app.gateway.semantic_scholar import SemanticScholarClient, SemanticScholarError

logger = get_logger(__name__)

S2_FIELDS = "paperId,externalIds,title,abstract,year,authors,openAccessPdf,url,publicationDate"
PIPELINE_PENDING_STATUSES = {"queued", "running", "waiting_for_user"}

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

# LLM prompt for external-query axis decomposition (Stage 3). The research
# question alone (long prose) is a poor Semantic Scholar relevance query; the
# LLM decomposes it into concise, term-rich search queries that target
# foundational methods, overlapping work, counter-evidence, and evaluation /
# critique literature — with the workspace's extracted methods/limitations as
# context so queries cross research axes with the workspace's named methods.
EXTERNAL_QUERY_AXIS_SYSTEM_PROMPT = 'You write effective search queries to find EXTERNAL papers that challenge, overlap with, or foundationally support a research question. The papers must be relevant to the question but are NOT required to be in the user\'s workspace.\n\nRules:\n- Write CONCISE keyword-style queries (3-8 words), never full sentences\n- Prefer SPECIFIC method names and established concept terms over generic topic phrases (e.g. "graph information bottleneck" or "invariant risk minimization", not just "interpretable GNN")\n- Turn at least 2 of the workspace\'s abbreviated method names into concrete queries using their FULL names, so the search finds the method\'s paper plus its variants and critiques\n- Cover distinct angles: foundational methods, overlapping prior work, counter-evidence / critiques, evaluation benchmarks, and the domain axis (e.g. distribution shift) when present\n- Do not quote the workspace paper titles verbatim\n- Never repeat the same idea in two queries\n\nAlso choose up to 4 workspace method names whose papers you want surfaced PRECISELY (these are searched by exact title, so give the full descriptive name — expand abbreviations). Prefer methods that are foundational or likely to have counter-evidence / variants. Do not list the same method twice.\n\nExamples of good queries:\n- "graph information bottleneck"\n- "invariant risk minimization out-of-distribution"\n- "saliency maps sanity checks"\n- "explanation robustness adversarial perturbations"\n- "graph rationalization environment augmentation"\n\nOutput a JSON object, nothing else:\n{"queries": ["...", "...", "..."], "exact_lookups": ["Method Full Name", "...", "..."]}'

EXTERNAL_FULLTEXT_ROLE_SYSTEM_PROMPT = """\
You classify whether an external research paper serves as counter-evidence for \
a research question, based on its FULL TEXT.

Categories:
- similar: same research area, closely related approach
- overlap: partially overlapping topic but different focus
- qualifies: adds caveats or limitations that constrain the research question
- contradicts: provides evidence against the research question
- unknown: cannot determine from the text

Rules:
- Be conservative: use "unknown" if ambiguous
- "contradicts" requires clear opposing evidence, not just a different focus
- Base your judgement on the FULL TEXT (not just the abstract) — e.g. an
  experiment that directly challenges the question's core assumption
- A paper that merely resembles the question is "similar"; only call it
  "qualifies" or "contradicts" when it explicitly challenges or constrains it

Output a JSON object, nothing else:
{"role": "similar|overlap|qualifies|contradicts|unknown", \
"confidence": 0.0-1.0}"""

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


# --------------------------------------------------------------------- helpers


def normalize_pdf_url(url: str) -> str:
    """Normalize an open-access PDF URL for download (W1).

    Semantic Scholar occasionally returns `http://` or scheme-relative
    (`//host/...`) URLs, and arXiv `abs` pages are HTML, not PDFs.
    ``download_pdf`` requires HTTPS, so normalize to a fetchable absolute
    ``https://`` URL here; non-fetchable schemes fall through to ``no_pdf``.
    """
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    elif url.lower().startswith("http://"):
        url = "https://" + url[len("http://"):]
    if url.startswith("https://arxiv.org/abs/"):
        url = url.replace("https://arxiv.org/abs/", "https://arxiv.org/pdf/")
    return url


def external_role(query: str, item: dict[str, Any]) -> str:
    """Cheap word-overlap heuristic role; LLM refinement follows in _judge_external_roles."""
    haystack = f"{item.get('title', '')} {item.get('abstract', '')}".lower()
    tokens = [token for token in re.findall(r"[a-z0-9]{4,}", query.lower()) if token not in {"with", "from", "under", "using"}]
    overlap = sum(token in haystack for token in tokens)
    return "similar" if overlap >= max(1, len(tokens) // 4) else "unknown"


def title_verified(name: str, title: str) -> bool:
    """Accept an exact-title lookup hit when the query words appear in the title."""
    query_words = set(re.findall(r"[a-z0-9]+", name.lower()))
    title_words = set(re.findall(r"[a-z0-9]+", title.lower()))
    if len(query_words) < 2:
        return False
    return query_words.issubset(title_words)



# --------------------------------------------------------------------- service


class ExternalRetrievalService:
    """External novelty search + OA full-text import orchestration.

    Composed by ``DiscoverService``; callers should go through that facade so
    existing tests using ``service._external_*`` keep working.
    """

    def __init__(
        self,
        db: Session,
        llm: LLMGateway,
        external_search: ExternalSearchPort,
        *,
        service=None,
    ) -> None:
        self.db = db
        self.llm = llm
        self.external_search = external_search
        self.service = service  # DiscoverService facade for shared helpers

    # ---------------------------------------------------------- pipeline state
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
        if self.service and self.service._cancelled(run):
            return self.service._cancelled_result(run)
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

    # ---------------------------------------------------------- query building
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
            return self.service._claim_text(item) if self.service else ""
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
            accumulate_tokens(run, resp)
            parsed = parse_json(resp.content)
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

    def _build_external_queries(self, run: DiscoverRun, primary: str) -> list[str]:
        """Backward-compatible list wrapper around ``_external_query_plan``."""
        return self._external_query_plan(run, primary)[0]

    # ---------------------------------------------------------------- verify
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
            external_summary = (run.stage_summaries or {}).get("external_search")
            if not isinstance(external_summary, dict) or external_summary.get("status") not in {
                "succeeded",
                "succeeded_partial",
                "succeeded_empty",
            }:
                run.stage_summaries = {
                    **(run.stage_summaries or {}),
                    "external_search": {
                        **(external_summary if isinstance(external_summary, dict) else {}),
                        "status": "succeeded",
                        "executed": True,
                        "candidate_count": existing,
                    },
                }
                self.db.commit()
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
        per_query: list[tuple[str, list[tuple[str, dict[str, Any]]]]] = []
        query_failures: list[dict[str, Any]] = []
        for position, query in enumerate(queries):
            try:
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
                per_query.append((query, q_results))
            except SemanticScholarError as exc:
                query_failures.append(
                    {
                        "query": query[:120],
                        "error": str(exc),
                        "status_code": exc.status_code,
                        "retryable": exc.status_code in {429, 502, 504},
                    }
                )
                logger.warning(
                    "discover.external_query_failed",
                    run_id=run.id,
                    query=query[:120],
                    error=str(exc),
                )

        if not per_query:
            last_failure = query_failures[-1] if query_failures else {}
            run.verification_status = "failed"
            run.stage_summaries = {
                **(run.stage_summaries or {}),
                "external_search": {
                    "status": "failed",
                    "error": last_failure.get("error", "all external search queries failed"),
                    "retryable": any(item["retryable"] for item in query_failures),
                    "executed": False,
                    "queries": [q[:120] for q in queries],
                    "successful_query_count": 0,
                    "failed_query_count": len(query_failures),
                    "query_failures": query_failures,
                },
            }
            self.db.commit()
            logger.warning(
                "discover.external_search_failed",
                run_id=run.id,
                error=last_failure.get("error", "all external search queries failed"),
            )
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
                if not title_verified(name, str(item["title"])):
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
            for source_query, q_results in per_query:
                if round_index < len(q_results):
                    pid, item = q_results[round_index]
                    if pid not in seen:
                        seen.add(pid)
                        merged.append((pid, item, source_query[:200]))
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
                role=external_role(primary, item), role_confidence=0.35,
                evidence_level="metadata_only", verification_status="unverified", snapshot_payload=item,
            )
            rows.append(row)
        self.db.add_all(rows)
        run.verification_status = "in_progress" if rows else "incomplete"
        search_status = (
            "succeeded_partial"
            if query_failures
            else ("succeeded" if rows else "succeeded_empty")
        )
        run.stage_summaries = {
            **(run.stage_summaries or {}),
            "external_search": {
                "status": search_status,
                "executed": True,
                "candidate_count": len(rows),
                "queries": [q[:120] for q in queries],
                "successful_query_count": len(per_query),
                "failed_query_count": len(query_failures),
                "query_failures": query_failures,
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

    # -------------------------------------------------------------- role judge
    def _judge_external_roles(
        self,
        run: DiscoverRun,
        query: str,
        candidates: list[DiscoverExternalCandidate],
    ) -> None:
        """LLM-refine external candidate roles.

        ``external_role`` is a cheap word-overlap heuristic that only yields
        similar/unknown. Stage 3 requires discriminating similar / overlap /
        qualify / contradict / unknown so Discover can tell which external
        paper might *challenge* an opportunity, not just resemble it.

        This batch-judges candidates against the research question using the
        LLM gateway. On failure it silently keeps the heuristic role (the
        candidate rows already carry a role from ``external_role``).
        """
        if not candidates:
            return
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
                accumulate_tokens(run, resp)
                parsed = parse_json(resp.content)
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

    def _judge_external_fulltext_roles(self, run: DiscoverRun, query: str) -> int:
        """Best-effort re-judge roles of verified full-text candidates (W1).

        Metadata-level roles (title+abstract) are refined once the imported
        paper's parsed text is available. Idempotent: rows already marked
        ``fulltext_role_judged`` are skipped; an LLM failure keeps the
        metadata role and marks ``fulltext_role_tried`` so a later resume can
        retry without looping forever.
        """
        rows = list(
            self.db.execute(
                select(DiscoverExternalCandidate).where(
                    DiscoverExternalCandidate.discover_run_id == run.id,
                    DiscoverExternalCandidate.verification_status == "verified",
                    DiscoverExternalCandidate.imported_paper_id.is_not(None),
                )
            ).scalars()
        )
        to_judge = [
            row for row in rows if not (row.snapshot_payload or {}).get("fulltext_role_judged")
        ]
        if not to_judge:
            return 0
        role_map = {
            "similar": "similar",
            "overlap": "overlap",
            "overlaps": "overlap",
            "qualifies": "qualifies",
            "qualify": "qualifies",
            "contradicts": "contradicts",
            "contradict": "contradicts",
            "unknown": "unknown",
        }
        judged = 0
        for row in to_judge:
            paper = self.db.get(Paper, row.imported_paper_id)
            if paper is None or not paper.parsed_text_artifact_id:
                continue
            text = self._read_paper_text(paper)[:4000]
            if not text.strip():
                continue
            try:
                resp = self.llm.chat_completion(
                    [
                        {"role": "system", "content": EXTERNAL_FULLTEXT_ROLE_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": f"RESEARCH QUESTION: {query[:300]}\n\nFULL TEXT:\n{text}",
                        },
                    ],
                    temperature=0.0,
                    max_tokens=500,
                    disable_thinking=True,
                )
                parsed = parse_json(resp.content)
                role = str((parsed or {}).get("role", "unknown")).lower()
                row.role = role_map.get(role, "unknown")
                try:
                    row.role_confidence = float((parsed or {}).get("confidence", 0.5))
                except (TypeError, ValueError):
                    row.role_confidence = 0.5
                row.snapshot_payload = {
                    **(row.snapshot_payload or {}),
                    "fulltext_role_judged": True,
                    "fulltext_role": row.role,
                }
                judged += 1
            except Exception as exc:
                logger.warning("discover.external_fulltext_role_failed", error=str(exc))
                row.snapshot_payload = {
                    **(row.snapshot_payload or {}),
                    "fulltext_role_tried": True,
                }
        self.db.commit()
        return judged

    def _read_paper_text(self, paper: Paper) -> str:
        """Read the imported paper's parsed plain text (best-effort)."""
        if not paper.parsed_text_artifact_id:
            return ""
        artifact = self.db.get(Artifact, paper.parsed_text_artifact_id)
        if artifact is None or artifact.is_deleted:
            return ""
        try:
            return ArtifactService(self.db).resolve_abs_path(artifact).read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            return ""

    # ----------------------------------------------------------------- import
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
            if not isinstance(pdf_url, str):
                row.verification_status = "no_pdf"
                continue
            pdf_url = normalize_pdf_url(pdf_url)
            if not pdf_url:
                row.verification_status = "no_pdf"
                continue
            try:
                content = client.download_pdf(pdf_url)
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
