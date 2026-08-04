"""Similar Work paper-level aggregation tests (RG-4 / D2).

The pipeline over-fetches from Milvus, then:
  1. drops chunks in low-value sections (References / Acknowledgments etc.)
  2. groups hits by paper and caps each paper at SIMILAR_WORK_MAX_CHUNKS_PER_PAPER
  3. reranks the diversified candidate pool

These tests mock Milvus/embedding and verify the post-aggregation shape
without needing a live Milvus instance.
"""

from __future__ import annotations

import json

import pytest

from app.domains.retrieval import service
from app.domains.retrieval.service import (
    LOW_VALUE_SECTIONS,
    SIMILAR_WORK_MAX_CHUNKS_PER_PAPER,
    _is_low_value_section,
)


# ==================================================================
# _is_low_value_section
# ==================================================================


def test_low_value_section_matches_references_case_insensitive() -> None:
    assert _is_low_value_section("References")
    assert _is_low_value_section("references")
    assert _is_low_value_section("REFERENCES")
    assert _is_low_value_section("References ")  # trailing space
    assert _is_low_value_section("  References  ")


def test_low_value_section_matches_other_citation_sections() -> None:
    for section in ("Bibliography", "Acknowledgments", "Acknowledgements",
                    "Appendix", "Author Contributions", "Supplementary Material"):
        assert _is_low_value_section(section), section


def test_low_value_section_passes_through_normal_sections() -> None:
    for section in ("Method", "Methods", "Methodology", "Introduction",
                    "Related Work", "Experiments", "Results",
                    "Discussion", "Conclusion", None, ""):
        assert not _is_low_value_section(section), section


def test_low_value_sections_is_explicit() -> None:
    # Snapshot: if we ever grow this list, we want a clear diff. Stable set of
    # currently-recognised low-value sections.
    assert LOW_VALUE_SECTIONS == frozenset({
        "references",
        "bibliography",
        "acknowledgments",
        "acknowledgements",
        "appendix",
        "author contributions",
        "supplementary",
        "supplementary material",
    })


# ==================================================================
# Service-level: paper aggregation + low-value filter
# ==================================================================


class _FakeEmbedding:
    def embed_one(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]

    def embed_texts(self, texts: list[str]):
        from types import SimpleNamespace
        return SimpleNamespace(embeddings=[[0.1, 0.2, 0.3, 0.4]] * len(texts))


class _FakeMilvus:
    """Replaces service.milvus_client. Returns hits verbatim per call (no dedup
    or filtering — that happens in the aggregation step we're testing)."""

    def __init__(self, hits: list[dict]) -> None:
        self.hits = hits

    def search(self, query_vector, workspace_id, top_k=10, *, paper_id=None, exclude_paper_ids=None, section=None):
        return list(self.hits)


def _patch(monkeypatch, hits: list[dict]) -> None:
    """Patch milvus_client.search + embedding + reranker so we only exercise the aggregation step."""
    monkeypatch.setattr(service, "milvus_client", _FakeMilvus(hits))
    monkeypatch.setattr(service, "get_embedding_gateway", _FakeEmbedding)

    # Bypass the reranker with a deterministic no-op that preserves input order.
    class _NoopReranker:
        def rerank(self, query, documents, *, top_n):
            from types import SimpleNamespace
            return SimpleNamespace(
                hits=[
                    SimpleNamespace(index=i, relevance_score=1.0 - i * 0.01)
                    for i in range(min(len(documents), top_n))
                ]
            )

    monkeypatch.setattr(service, "get_reranker_gateway", lambda: _NoopReranker())


def _write_source_chunks(tmp_path, workspace_id: str, paper_id: str, n: int = 3) -> None:
    chunk_dir = tmp_path / workspace_id
    chunk_dir.mkdir(parents=True, exist_ok=True)
    (chunk_dir / f"{paper_id}.jsonl").write_text(
        "\n".join(
            json.dumps({
                "chunk_id": f"src-{i}",
                "workspace_id": workspace_id,
                "paper_id": paper_id,
                "source_artifact_id": "art-1",
                "chunk_index": i,
                "text": f"source chunk {i}",
                "start_char": 0,
                "end_char": 10,
            })
            for i in range(n)
        ),
        encoding="utf-8",
    )


def _hit(chunk_id: str, paper_id: str, *, section: str | None = "Method", score: float = 0.5) -> dict:
    return {
        "chunk_id": chunk_id,
        "workspace_id": "ws-1",
        "paper_id": paper_id,
        "source_artifact_id": "art-x",
        "chunk_index": 1,
        "section": section,
        "text": f"text {chunk_id}",
        "score": score,
    }


def test_similar_work_drops_low_value_sections(monkeypatch, tmp_path) -> None:
    _write_source_chunks(tmp_path, "ws-1", "p-src")
    monkeypatch.setattr(service, "DATA_ROOT", tmp_path)
    hits = [
        _hit("c1", "p-other", section="Method", score=0.9),
        _hit("c2", "p-other", section="References", score=0.95),  # should drop
        _hit("c3", "p-other", section="Acknowledgments", score=0.99),  # should drop
    ]
    _patch(monkeypatch, hits)

    resp = service.find_similar_work("ws-1", "p-src", top_k=10, use_reranker=True)
    assert len(resp.items) == 1
    assert resp.items[0].chunk_id == "c1"
    assert resp.filters_applied["low_value_section_filter"] is True


def test_similar_work_caps_chunks_per_paper(monkeypatch, tmp_path) -> None:
    _write_source_chunks(tmp_path, "ws-1", "p-src")
    monkeypatch.setattr(service, "DATA_ROOT", tmp_path)
    # p-A has 4 high-quality hits, p-B has 1. Without cap, p-A dominates.
    hits = [
        _hit(f"a{i}", "p-A", score=0.9 - i * 0.05) for i in range(4)
    ] + [_hit("b1", "p-B", score=0.7)]
    _patch(monkeypatch, hits)

    resp = service.find_similar_work("ws-1", "p-src", top_k=10, use_reranker=True)
    # With cap=2: 2 from p-A + 1 from p-B = 3
    by_paper: dict[str, int] = {}
    for item in resp.items:
        by_paper[item.paper_id or ""] = by_paper.get(item.paper_id or "", 0) + 1
    assert by_paper.get("p-A", 0) <= SIMILAR_WORK_MAX_CHUNKS_PER_PAPER
    assert "p-B" in by_paper  # diversity preserved
    assert resp.filters_applied["max_chunks_per_paper"] == SIMILAR_WORK_MAX_CHUNKS_PER_PAPER


def test_similar_work_falls_back_when_all_low_value(monkeypatch, tmp_path) -> None:
    """If every candidate is a low-value section chunk, return them anyway
    rather than an empty Top-K (the section classifier can fail)."""
    _write_source_chunks(tmp_path, "ws-1", "p-src")
    monkeypatch.setattr(service, "DATA_ROOT", tmp_path)
    hits = [
        _hit("r1", "p-A", section="References", score=0.9),
        _hit("r2", "p-A", section="References", score=0.8),
    ]
    _patch(monkeypatch, hits)

    resp = service.find_similar_work("ws-1", "p-src", top_k=10, use_reranker=True)
    assert len(resp.items) == 2


def test_similar_work_paper_diversity(monkeypatch, tmp_path) -> None:
    """Over-fetch + per-paper cap should keep Top-10 paper-diverse when the
    corpus supports it (no single paper can occupy >50% of Top-10)."""
    _write_source_chunks(tmp_path, "ws-1", "p-src")
    monkeypatch.setattr(service, "DATA_ROOT", tmp_path)
    # 10 distinct papers, 3 chunks each → after cap (2/paper), each contributes 2.
    hits = []
    for p_idx in range(10):
        for c_idx in range(3):
            hits.append(_hit(f"p{p_idx}-c{c_idx}", f"p-{p_idx}", score=0.9 - p_idx * 0.05 - c_idx * 0.01))
    _patch(monkeypatch, hits)

    resp = service.find_similar_work("ws-1", "p-src", top_k=10, use_reranker=True)
    assert len(resp.items) == 10
    distinct_papers = len({item.paper_id for item in resp.items})
    # Without cap, the highest-scoring paper alone could fill Top-10.
    assert distinct_papers >= 5  # at least half the Top-10 are distinct papers
    # Source paper must not appear.
    assert "p-src" not in {item.paper_id for item in resp.items}


def test_similar_work_source_paper_still_excluded(monkeypatch, tmp_path) -> None:
    _write_source_chunks(tmp_path, "ws-1", "p-src")
    monkeypatch.setattr(service, "DATA_ROOT", tmp_path)
    # Even if Milvus returned the source's chunks somehow, the source is
    # excluded by the service contract.
    hits = [
        _hit("src1", "p-src", score=0.99),  # MUST NOT appear
        _hit("o1", "p-other", score=0.5),
    ]
    _patch(monkeypatch, hits)

    resp = service.find_similar_work("ws-1", "p-src", top_k=10, use_reranker=True)
    assert all(item.paper_id != "p-src" for item in resp.items)
    assert any(item.paper_id == "p-other" for item in resp.items)
    assert "p-src" in resp.filters_applied["excluded_paper_ids"]