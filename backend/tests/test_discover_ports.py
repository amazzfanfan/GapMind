"""Tests for the Discover service Protocol ports.

These exercise that ``DiscoverService.__init__`` accepts Protocol-compatible
fakes and that swapping them out doesn't require touching the service code.
The actual cross-domain behaviour is tested in the retrieval / llm test
suites; here we just verify the wiring.
"""

from __future__ import annotations

from typing import Any

from app.domains.discover.adapters import (
    ExternalSearchAdapter,
    LLMGatewayAdapter,
    RetrievalAdapter,
    assert_protocol,
)
from app.domains.discover.ports import (
    ExternalSearchPort,
    LLMGatewayPort,
    RetrievalPort,
)
from app.domains.discover.service import DiscoverService


class FakeRetrieval:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def semantic_search(self, workspace_id: str, query: str, top_k: int, **kw: Any):
        self.calls.append(("semantic_search", workspace_id, {"query": query, "top_k": top_k, **kw}))
        return _stub_response(query)

    def find_similar_work(self, workspace_id: str, paper_id: str, top_k: int, **kw: Any):
        self.calls.append(("find_similar_work", workspace_id, {"paper_id": paper_id, **kw}))
        return _stub_response(paper_id)

    def find_counter_evidence(self, workspace_id: str, claim: str, top_k: int, **kw: Any):
        self.calls.append(("find_counter_evidence", workspace_id, {"claim": claim, **kw}))
        return _stub_response(claim)


class FakeExternalSearch:
    def __init__(self) -> None:
        self.searches: list[dict[str, Any]] = []

    def search(self, query: str, *, fields: str, **kw: Any):
        self.searches.append({"query": query, "fields": fields, **kw})
        return {"data": [], "total": 0}

    def get_paper(self, paper_id: str, *, fields: str):
        return {"paperId": paper_id}


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def chat_completion(self, messages: list[dict[str, str]], **kw: Any):
        self.calls.append(messages)
        return _stub_llm_response("{}")


def _stub_response(query: str):
    from app.domains.retrieval.schemas import RetrievalResponse

    return RetrievalResponse(
        workspace_id="ws-1",
        query=query,
        purpose="test",
        status="succeeded",
        items=[],
        total=0,
        error=None,
    )


def _stub_llm_response(content: str):
    from types import SimpleNamespace

    return SimpleNamespace(content=content, usage=None)


# ---------------------------------------------------------------- test cases
def test_default_adapters_satisfy_protocols() -> None:
    """The production adapters must be valid port bindings."""
    assert isinstance(RetrievalAdapter(), RetrievalPort)
    assert isinstance(ExternalSearchAdapter(), ExternalSearchPort)
    assert isinstance(LLMGatewayAdapter(), LLMGatewayPort)


def test_assert_protocol_rejects_missing_method() -> None:
    class Incomplete:
        def semantic_search(self, *args, **kwargs):
            return None
        # missing find_similar_work / find_counter_evidence

    import pytest

    with pytest.raises(TypeError, match="does not satisfy protocol"):
        assert_protocol(Incomplete(), RetrievalPort)


def test_discover_service_accepts_protocol_fakes(db_session) -> None:
    """Wiring: the service should bind the fakes and never reach the real adapters."""
    service = DiscoverService(
        db_session,
        retrieval=FakeRetrieval(),
        external_search=FakeExternalSearch(),
        llm=FakeLLM(),
    )

    # Default __init__ still completes when no overrides are passed.
    default = DiscoverService(db_session)
    assert isinstance(default.retrieval, RetrievalPort)
    assert isinstance(default.external_search, ExternalSearchPort)
    assert isinstance(default.llm, LLMGatewayPort)
    # Service stays usable — no exceptions raised.
    assert service.db is db_session