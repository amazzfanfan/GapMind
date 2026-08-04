"""Smoke tests for Knowledge read-only API (Phase 1b).

Knowledge content is written by the extraction pipeline in Phase 3, so
Phase 1b only verifies that the endpoints respond with empty lists and
that workspace scoping works.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.domains.artifact.service import ArtifactService
from app.domains.knowledge.models import (
    CanonicalEntity,
    EvidenceSpan,
    KnowledgeItem,
    KnowledgeRelation,
    PaperMention,
)
from app.domains.paper.models import Paper


def _create_workspace(client: TestClient, name: str = "WS") -> dict:
    resp = client.post("/api/v1/workspaces", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_list_knowledge_empty(client: TestClient) -> None:
    ws = _create_workspace(client)
    resp = client.get(f"/api/v1/workspaces/{ws['id']}/knowledge")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_list_relations_empty(client: TestClient) -> None:
    ws = _create_workspace(client)
    resp = client.get(f"/api/v1/workspaces/{ws['id']}/knowledge/relations")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_knowledge_graph_empty(client: TestClient) -> None:
    ws = _create_workspace(client)
    resp = client.get(f"/api/v1/workspaces/{ws['id']}/knowledge/graph")
    assert resp.status_code == 200
    assert resp.json()["nodes"] == []
    assert resp.json()["edges"] == []


def test_knowledge_graph_returns_self_contained_nodes_and_edges(
    client: TestClient,
    db_session,
) -> None:
    ws = _create_workspace(client)
    source = KnowledgeItem(
        workspace_id=ws["id"],
        paper_id=None,
        type="method",
        canonical_name="Method A",
        content={"description": "A"},
        source_provenance={},
        created_by="agent",
        confidence=0.9,
        status="extracted_candidate",
        is_deleted=False,
    )
    target = KnowledgeItem(
        workspace_id=ws["id"],
        paper_id=None,
        type="dataset",
        canonical_name="Dataset B",
        content={"description": "B"},
        source_provenance={},
        created_by="agent",
        confidence=0.8,
        status="extracted_candidate",
        is_deleted=False,
    )
    db_session.add_all([source, target])
    db_session.flush()
    db_session.add(
        KnowledgeRelation(
            workspace_id=ws["id"],
            source_id=source.id,
            target_id=target.id,
            relation_type="evaluates_on",
            confidence=0.75,
            payload={},
            is_deleted=False,
        )
    )
    db_session.commit()

    resp = client.get(f"/api/v1/workspaces/{ws['id']}/knowledge/graph")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {node["label"] for node in body["nodes"]} == {"Method A", "Dataset B"}
    assert body["edges"][0]["source"] == source.id
    assert body["edges"][0]["target"] == target.id


def test_get_knowledge_item_not_found(client: TestClient) -> None:
    ws = _create_workspace(client)
    resp = client.get(
        f"/api/v1/workspaces/{ws['id']}/knowledge/00000000-0000-0000-0000-000000000000"
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "knowledge_item_not_found"


def test_knowledge_workspace_not_found(client: TestClient) -> None:
    resp = client.get("/api/v1/workspaces/00000000-0000-0000-0000-000000000000/knowledge")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "workspace_not_found"


def test_knowledge_item_review_confirm_and_edit(client: TestClient, db_session) -> None:
    ws = _create_workspace(client)
    item = KnowledgeItem(
        workspace_id=ws["id"], type="claim", canonical_name="Old claim",
        content={"statement": "old"}, source_provenance={}, created_by="agent",
        confidence=0.5, status="extracted_candidate", is_deleted=False,
    )
    db_session.add(item)
    db_session.commit()

    response = client.patch(
        f"/api/v1/workspaces/{ws['id']}/knowledge/{item.id}/review",
        json={"action": "edit", "canonical_name": "Reviewed claim", "content": {"statement": "new"}, "note": "checked"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["canonical_name"] == "Reviewed claim"
    assert body["content"]["statement"] == "new"
    assert body["status"] == "human_confirmed"
    assert body["review_note"] == "checked"


def test_evidence_context_and_markdown_download(client: TestClient, db_session) -> None:
    ws = _create_workspace(client)
    artifact = ArtifactService(db_session).save_upload(
        workspace_id=ws["id"], filename="paper.md", content=b"# Intro\nEvidence sentence.",
        mime_type="text/markdown", kind="parsed_markdown",
    )
    paper = Paper(
        workspace_id=ws["id"], title="Evidence paper", authors=[], source="manual",
        parsed_markdown_artifact_id=artifact.id, parse_status="parsed", is_deleted=False,
    )
    item = KnowledgeItem(
        workspace_id=ws["id"], paper_id=paper.id, type="claim", canonical_name="Claim",
        content={"statement": "Evidence sentence."}, source_provenance={}, created_by="agent",
        confidence=0.8, status="extracted_candidate", is_deleted=False,
    )
    db_session.add_all([paper, item])
    db_session.flush()
    db_session.add(EvidenceSpan(
        workspace_id=ws["id"], knowledge_item_id=item.id, paper_id=paper.id,
        artifact_id=artifact.id, artifact_kind="parsed_markdown", artifact_version="v1",
        start_char=7, end_char=24, text="Evidence sentence.", relation="supports", confidence=0.8,
    ))
    db_session.commit()

    context = client.get(f"/api/v1/workspaces/{ws['id']}/knowledge/{item.id}/evidence/context")
    assert context.status_code == 200, context.text
    assert context.json()["content"] == "# Intro\nEvidence sentence."
    assert context.json()["spans"][0]["start_char"] == 7

    download = client.get(f"/api/v1/workspaces/{ws['id']}/artifacts/{artifact.id}/download")
    assert download.status_code == 200
    assert download.content == b"# Intro\nEvidence sentence."


def test_graph_contains_layered_nodes_and_expands_entity_neighbors(
    client: TestClient, db_session
) -> None:
    ws = _create_workspace(client)
    paper = Paper(
        workspace_id=ws["id"], title="Layered paper", authors=[], source="manual", is_deleted=False,
    )
    entity = CanonicalEntity(
        workspace_id=ws["id"], type="method", canonical_name="Method A",
        normalization_key="methoda", aliases=[], status="extracted_candidate", is_deleted=False,
    )
    db_session.add_all([paper, entity])
    db_session.flush()
    item = KnowledgeItem(
        workspace_id=ws["id"], paper_id=paper.id, canonical_entity_id=entity.id,
        type="method", canonical_name="Method A", content={"description": "A"},
        source_provenance={}, created_by="agent", confidence=0.9,
        status="extracted_candidate", is_deleted=False,
    )
    db_session.add(item)
    db_session.flush()
    db_session.add(PaperMention(
        workspace_id=ws["id"], paper_id=paper.id, canonical_entity_id=entity.id,
        knowledge_item_id=item.id, mention_text="Method A", start_char=0, end_char=8,
        confidence=0.9, status="extracted_candidate", is_deleted=False,
    ))
    db_session.commit()

    graph = client.get(f"/api/v1/workspaces/{ws['id']}/knowledge/graph?limit=20")
    assert graph.status_code == 200, graph.text
    assert {node["node_kind"] for node in graph.json()["nodes"]} >= {
        "knowledge", "paper", "canonical_entity", "paper_mention"
    }

    neighbors = client.get(
        f"/api/v1/workspaces/{ws['id']}/knowledge/graph/neighbors/entity:{entity.id}"
    )
    assert neighbors.status_code == 200, neighbors.text
    assert any(node["id"] == item.id for node in neighbors.json()["nodes"])
