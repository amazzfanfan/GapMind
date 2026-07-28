"""Semantic Scholar Academic Graph API client.

The API key is intentionally kept on the backend. The frontend talks to our
own API and never receives the Semantic Scholar credential.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.semantic_scholar_control import (
    read_search_cache,
    search_cache_key,
    wait_for_request_slot,
    write_search_cache,
)


class SemanticScholarError(Exception):
    """An error returned by, or raised while calling, Semantic Scholar."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class SemanticScholarClient:
    """Small synchronous client for the Academic Graph paper endpoints."""

    def __init__(self, timeout: float = 20.0) -> None:
        self.base_url = settings.semantic_scholar_base_url.rstrip("/") + "/"
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        # API keys are optional for Semantic Scholar, but recommended. Do not
        # send an empty header when local development has no key configured.
        if settings.semantic_scholar_api_key:
            return {"x-api-key": settings.semantic_scholar_api_key}
        return {}

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        response: httpx.Response | None = None
        retry_count = max(0, settings.semantic_scholar_retry_count)
        for attempt in range(retry_count + 1):
            try:
                wait_for_request_slot()
                with httpx.Client(
                    base_url=self.base_url,
                    headers=self._headers(),
                    timeout=self.timeout,
                ) as client:
                    response = client.get(path.lstrip("/"), params=params)
            except httpx.TimeoutException as exc:
                raise SemanticScholarError(
                    "Semantic Scholar request timed out", status_code=504
                ) from exc
            except httpx.RequestError as exc:
                raise SemanticScholarError(
                    f"Semantic Scholar request failed: {exc}", status_code=502
                ) from exc

            if response.status_code != 429 or attempt >= retry_count:
                break
            retry_after = response.headers.get("Retry-After")
            try:
                retry_after_seconds = float(retry_after) if retry_after else 0.0
            except ValueError:
                retry_after_seconds = 0.0
            time.sleep(
                max(
                    retry_after_seconds,
                    settings.semantic_scholar_retry_backoff * (2**attempt),
                )
            )

        if response is None:
            raise SemanticScholarError(
                "Semantic Scholar returned no response", status_code=502
            )

        if response.is_error:
            message = response.text[:500] or response.reason_phrase
            try:
                body = response.json()
                if isinstance(body, dict) and body.get("message"):
                    message = str(body["message"])
            except ValueError:
                pass
            raise SemanticScholarError(message, status_code=response.status_code)

        try:
            payload = response.json()
        except ValueError as exc:
            raise SemanticScholarError(
                "Semantic Scholar returned invalid JSON", status_code=502
            ) from exc
        if not isinstance(payload, dict):
            raise SemanticScholarError(
                "Semantic Scholar returned an unexpected response", status_code=502
            )
        return payload

    def search(
        self,
        *,
        query: str,
        fields: str,
        sort: str,
        limit: int,
        offset: int = 0,
        token: str | None = None,
        **filters: Any,
    ) -> dict[str, Any]:
        """Search papers using relevance search or bulk sorted search."""

        is_relevance = sort == "relevance"
        path = "paper/search" if is_relevance else "paper/search/bulk"
        params: dict[str, Any] = {
            "query": query,
            "fields": fields,
            "limit": limit,
        }
        params.update({key: value for key, value in filters.items() if value is not None})

        if is_relevance:
            params["offset"] = offset
        else:
            params["sort"] = sort
            if token:
                params["token"] = token

        cache_key = search_cache_key(params)
        cached = read_search_cache(cache_key)
        if cached is not None:
            return cached
        payload = self._get(path, params)
        write_search_cache(cache_key, payload)
        return payload

    def download_pdf(self, url: str, *, max_bytes: int = 50 * 1024 * 1024) -> bytes:
        """Download and validate an open-access PDF."""
        if not url.lower().startswith("https://"):
            raise SemanticScholarError(
                "Open-access PDF URL must use HTTPS", status_code=400
            )
        try:
            with httpx.Client(
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
                headers={"User-Agent": "GapMind/1.0"},
            ) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > max_bytes:
                        raise SemanticScholarError(
                            "Open-access PDF is too large", status_code=413
                        )
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise SemanticScholarError(
                                "Open-access PDF is too large", status_code=413
                            )
                        chunks.append(chunk)
        except SemanticScholarError:
            raise
        except httpx.TimeoutException as exc:
            raise SemanticScholarError(
                "Open-access PDF download timed out", status_code=504
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise SemanticScholarError(
                f"Open-access PDF download failed: HTTP {exc.response.status_code}",
                status_code=502,
            ) from exc
        except (httpx.RequestError, ValueError) as exc:
            raise SemanticScholarError(
                f"Open-access PDF download failed: {exc}", status_code=502
            ) from exc

        content = b"".join(chunks)
        if not content.startswith(b"%PDF"):
            raise SemanticScholarError(
                "Downloaded open-access file is not a PDF", status_code=502
            )
        return content

    def get_paper(self, paper_id: str, *, fields: str) -> dict[str, Any]:
        """Fetch one paper by Semantic Scholar, DOI, arXiv, or Corpus ID."""

        encoded_id = quote(paper_id, safe=":")
        return self._get(f"paper/{encoded_id}", {"fields": fields})
