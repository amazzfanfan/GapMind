"""Reranker Gateway - SiliconFlow BGE-reranker integration.

Provides cross-encoder reranking for retrieval candidates.
Uses SiliconFlow's /v1/rerank endpoint (same API key as embedding).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RerankHit:
    """A single reranked result."""

    index: int  # original index in the input documents list
    relevance_score: float


@dataclass
class RerankResult:
    """Normalized rerank response."""

    hits: list[RerankHit] = field(default_factory=list)
    model: str = ""
    latency_ms: float = 0.0


class RerankerGateway:
    """Wrapper over SiliconFlow's rerank endpoint.

    Model: BAAI/bge-reranker-v2-m3 (cross-encoder, multilingual).
    Endpoint: POST {base_url}/rerank
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.siliconflow_api_key
        # Rerank endpoint shares the same base URL as embedding
        self.base_url = (base_url if base_url is not None else settings.siliconflow_base_url).rstrip("/")
        self.model = model if model is not None else settings.reranker_model
        self.timeout = timeout

    def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int | None = None,
    ) -> RerankResult:
        """Rerank documents by relevance to query.

        Args:
            query: The search query or claim text.
            documents: List of passage texts to rerank.
            top_n: Return only top N results (default: all).

        Returns:
            RerankResult with hits sorted by relevance_score descending.
        """
        if not documents:
            return RerankResult(model=self.model)

        if not self.api_key:
            raise RuntimeError(
                "SILICONFLOW_API_KEY is not set. Configure the repo-root .env."
            )

        import time

        start = time.perf_counter()

        payload: dict = {
            "model": self.model,
            "query": query,
            "documents": documents,
        }
        if top_n is not None:
            payload["top_n"] = top_n

        url = f"{self.base_url}/rerank"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        logger.info(
            "reranker.request",
            model=self.model,
            query_len=len(query),
            doc_count=len(documents),
            top_n=top_n,
        )

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        latency = (time.perf_counter() - start) * 1000

        hits = [
            RerankHit(
                index=item["index"],
                relevance_score=item["relevance_score"],
            )
            for item in data.get("results", [])
        ]
        # Sort by relevance descending
        hits.sort(key=lambda h: h.relevance_score, reverse=True)

        logger.info(
            "reranker.response",
            model=self.model,
            hit_count=len(hits),
            latency_ms=round(latency, 1),
        )

        return RerankResult(hits=hits, model=self.model, latency_ms=latency)

    def ping(self) -> bool:
        """Check if API key is configured."""
        return bool(self.api_key)


_gateway: RerankerGateway | None = None


def get_reranker_gateway() -> RerankerGateway:
    """Singleton accessor for the Reranker gateway."""
    global _gateway
    if _gateway is None:
        _gateway = RerankerGateway()
    return _gateway
