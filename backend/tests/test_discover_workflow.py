from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

from app.domains.artifact.models import Artifact
from app.domains.discover.models import DiscoverExternalCandidate, DiscoverRun
from app.domains.discover.service import DiscoverService, resume_discover_runs_for_paper
from app.domains.knowledge.models import EvidenceSpan, KnowledgeItem
from app.domains.paper.models import Paper
from app.domains.retrieval.schemas import RetrievalResponse, RetrievalResultItem
from app.domains.task.models import Task
from app.domains.workspace.models import Workspace


def _supporting_item(paper_id: str, artifact_id: str, text: str, chunk_id: str) -> RetrievalResultItem:
    return RetrievalResultItem(
        paper_id=paper_id,
        paper_title="Paper",
        artifact_id=artifact_id,
        chunk_id=chunk_id,
        text=text,
        evidence_level="full_text",
        judgement="supports",
        source_scope="workspace",
    )


def _run(workspace_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=str(uuid4()),
        workspace_id=workspace_id,
        stage_summaries={"external_search": {"status": "succeeded", "executed": True}},
    )


def _supporting_response(items: list[RetrievalResultItem]) -> RetrievalResponse:
    return RetrievalResponse(
        workspace_id="workspace",
        purpose="supporting_evidence",
        status="succeeded",
        items=items,
        total=len(items),
    )


def _candidate() -> dict:
    return {
        "problem_statement": "robust graph learning behavior under shift",
        "candidate_hypothesis": "robust graph learning improves under shift",
        "why_existing_work_is_insufficient": "existing graph learning evidence is limited",
    }


def test_similar_work_cannot_count_as_supporting_evidence(db_session) -> None:
    workspace_id = str(uuid4())
    service = DiscoverService(db_session)
    similar = _supporting_response([
        _supporting_item(str(uuid4()), str(uuid4()), "robust graph learning behavior under shift", "s1"),
        _supporting_item(str(uuid4()), str(uuid4()), "robust graph learning improves under shift", "s2"),
    ])
    counter = RetrievalResponse(workspace_id=workspace_id, purpose="counter_evidence", status="succeeded")
    gate = service._evidence_gate(_run(workspace_id), candidate=_candidate(), supporting=_supporting_response([]), counter=counter)
    assert gate["verified"] is False
    assert gate["independent_full_text_papers"] == 0


def test_metadata_only_and_duplicate_chunks_do_not_pass_gate(db_session) -> None:
    workspace_id = str(uuid4())
    paper_id = str(uuid4())
    artifact_id = str(uuid4())
    workspace = Workspace(id=workspace_id, name="Gate workspace", is_archived=False)
    paper = Paper(id=paper_id, workspace_id=workspace_id, title="Paper", authors=[], source="manual", is_deleted=False)
    artifact = Artifact(id=artifact_id, workspace_id=workspace_id, kind="parsed_markdown", file_path="missing.md", size_bytes=0, is_deleted=False)
    item = KnowledgeItem(id=str(uuid4()), workspace_id=workspace_id, paper_id=paper_id, type="claim", canonical_name="claim", content={}, source_provenance={}, created_by="agent", is_deleted=False)
    db_session.add_all([workspace, paper, artifact, item])
    db_session.flush()
    db_session.add(EvidenceSpan(id=str(uuid4()), workspace_id=workspace_id, knowledge_item_id=item.id, paper_id=paper_id, artifact_id=artifact_id, relation="supports", text="robust graph learning behavior under shift", start_char=0, end_char=44, confidence=0.9))
    db_session.commit()
    service = DiscoverService(db_session)
    duplicate = _supporting_item(paper_id, artifact_id, "robust graph learning behavior under shift", "c1")
    duplicate2 = _supporting_item(paper_id, artifact_id, "robust graph learning improves under shift", "c2")
    metadata = _supporting_item(str(uuid4()), str(uuid4()), "robust graph learning evidence", "m1")
    metadata.evidence_level = "metadata_only"
    counter = RetrievalResponse(workspace_id=workspace_id, purpose="counter_evidence", status="succeeded")
    gate = service._evidence_gate(_run(workspace_id), candidate=_candidate(), supporting=_supporting_response([duplicate, duplicate2, metadata]), counter=counter)
    assert gate["verified"] is False
    assert gate["independent_full_text_papers"] == 1


def test_two_span_backed_supports_papers_pass_gate(db_session) -> None:
    workspace_id = str(uuid4())
    workspace = Workspace(id=workspace_id, name="Gate workspace", is_archived=False)
    items = []
    retrieval = []
    for index in range(2):
        paper_id = str(uuid4())
        artifact_id = str(uuid4())
        paper = Paper(id=paper_id, workspace_id=workspace_id, title=f"Paper {index}", authors=[], source="manual", is_deleted=False)
        artifact = Artifact(id=artifact_id, workspace_id=workspace_id, kind="parsed_markdown", file_path=f"paper-{index}.md", size_bytes=1, is_deleted=False)
        item = KnowledgeItem(id=str(uuid4()), workspace_id=workspace_id, paper_id=paper_id, type="claim", canonical_name="claim", content={}, source_provenance={}, created_by="agent", is_deleted=False)
        items.append((paper, artifact, item))
        retrieval.append(_supporting_item(paper_id, artifact_id, "robust graph learning behavior under shift", f"chunk-{index}"))
    db_session.add(workspace)
    db_session.flush()
    for paper, artifact, item in items:
        db_session.add_all([paper, artifact, item])
        db_session.flush()
        db_session.add(EvidenceSpan(id=str(uuid4()), workspace_id=workspace_id, knowledge_item_id=item.id, paper_id=paper.id, artifact_id=artifact.id, relation="supports", text="robust graph learning behavior under shift", start_char=0, end_char=44, confidence=0.9))
    db_session.commit()
    service = DiscoverService(db_session)
    counter = RetrievalResponse(workspace_id=workspace_id, purpose="counter_evidence", status="succeeded")
    gate = service._evidence_gate(_run(workspace_id), candidate=_candidate(), supporting=_supporting_response(retrieval), counter=counter)
    assert gate["verified"] is True
    assert gate["independent_full_text_papers"] == 2
    assert gate["evidence_coverage"] >= 0.6


def test_fulltext_pipeline_resumes_waiting_run_once_and_marks_candidate_verified(db_session) -> None:
    workspace_id = str(uuid4())
    paper_id = str(uuid4())
    artifact_id = str(uuid4())
    run_id = str(uuid4())
    task_id = str(uuid4())
    workspace = Workspace(id=workspace_id, name="Resume workspace", is_archived=False)
    paper = Paper(id=paper_id, workspace_id=workspace_id, title="Imported", authors=[], source="semantic_scholar", parse_status="parsed", parsed_markdown_artifact_id=artifact_id, parsed_text_artifact_id=str(uuid4()), extract_status="extracted", is_deleted=False)
    artifact = Artifact(id=artifact_id, workspace_id=workspace_id, kind="parsed_markdown", file_path="paper.md", size_bytes=1, is_deleted=False)
    item = KnowledgeItem(id=str(uuid4()), workspace_id=workspace_id, paper_id=paper_id, type="claim", canonical_name="claim", content={}, source_provenance={}, created_by="agent", is_deleted=False)
    db_session.add_all([workspace, paper, artifact, item])
    db_session.flush()
    db_session.add(EvidenceSpan(id=str(uuid4()), workspace_id=workspace_id, knowledge_item_id=item.id, paper_id=paper_id, artifact_id=artifact_id, relation="supports", text="supporting evidence", start_char=0, end_char=19, confidence=0.9))
    task = Task(id=task_id, workspace_id=workspace_id, task_type="discover_agent", status="waiting_for_user", progress=0.68, payload={"run_id": run_id}, is_deleted=False)
    run = DiscoverRun(id=run_id, workspace_id=workspace_id, task_id=task_id, input_topic="topic", input_payload={}, scope={}, config={}, status="waiting_for_fulltext", stage="fulltext_verification", progress=0.68, verification_status="in_progress", stage_summaries={"external_search": {"status": "succeeded"}})
    candidate = DiscoverExternalCandidate(id=str(uuid4()), discover_run_id=run_id, query="topic", rank=1, external_paper_id="S2-1", title="Imported", authors=[], evidence_level="metadata_only", verification_status="imported_pending_parse", imported_paper_id=paper_id, snapshot_payload={})
    embed_task = Task(id=str(uuid4()), workspace_id=workspace_id, task_type="embed_chunks", status="succeeded", progress=1.0, payload={"paper_id": paper_id}, result={"indexed_count": 3}, is_deleted=False)
    db_session.add_all([task, run, candidate, embed_task])
    db_session.commit()

    with patch("app.workers.tasks.run_discover.spawn_discover_task", return_value="resumed-celery-id"):
        resume_discover_runs_for_paper(db_session, paper_id, workspace_id)

    db_session.refresh(run)
    db_session.refresh(candidate)
    assert run.status == "queued"
    assert candidate.verification_status == "verified"
    assert db_session.get(Task, task_id).status == "running"
    assert db_session.get(Task, task_id).celery_task_id == "resumed-celery-id"
