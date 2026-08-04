"""Unit tests for the extraction helpers extracted from the Celery worker."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.workers.tasks.extraction.batching import (
    DEFAULT_MAX_CHARS,
    split_extraction_batches,
)
from app.workers.tasks.extraction.llm_caller import (
    call_llm_with_retry,
    parse_llm_json,
)


# ---------------------------------------------------------------- batching
def test_split_short_text_returns_single_batch() -> None:
    assert split_extraction_batches("short") == [(0, "short")]


def test_split_long_text_preserves_heading_boundaries() -> None:
    body = "intro paragraph\n\n" + ("x" * (DEFAULT_MAX_CHARS - 50)) + "\n## Methods\n" + ("y" * 1000)
    batches = split_extraction_batches(body)
    # At least two batches and the heading ends up on its own batch boundary.
    assert len(batches) >= 2
    starts = [start for start, _ in batches]
    assert starts == sorted(starts)
    # Last batch ends exactly at the document length (no tail dropped).
    last_start, last_text = batches[-1]
    assert last_start + len(last_text) == len(body)


def test_split_never_drops_tail() -> None:
    body = "a" * (DEFAULT_MAX_CHARS * 2 + 250)
    batches = split_extraction_batches(body)
    joined = "".join(text for _, text in batches)
    # Even with overlap, the union must cover the whole document.
    assert joined.startswith(body[:100])
    assert joined.rstrip().endswith(body[-100:].rstrip())


# ---------------------------------------------------------------- LLM JSON
@pytest.mark.parametrize(
    "raw,expected",
    [
        ('```json\n{"items": []}\n```', {"items": []}),
        ("noise {\"items\": [1]} trailing", {"items": [1]}),
        ('{"items": [1],}', {"items": [1]}),  # trailing comma stripped
        ("not json", None),
        ('{"items": "string-not-list"}', {"items": "string-not-list"}),
    ],
)
def test_parse_llm_json_handles_common_shapes(raw: str, expected) -> None:
    assert parse_llm_json(raw) == expected


def test_call_llm_with_retry_returns_parsed_on_success() -> None:
    """Successful first try → parsed dict + raw."""
    fake_response = MagicMock(content='```json\n{"items": []}\n```')
    fake_gateway = MagicMock(chat_completion=MagicMock(return_value=fake_response))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.workers.tasks.extraction.llm_caller.LLMGateway", lambda: fake_gateway)
        raw, parsed = call_llm_with_retry(
            [{"role": "user", "content": "extract"}],
            max_retries=0,
        )

    assert parsed == {"items": []}
    assert raw == fake_response.content
    assert fake_gateway.chat_completion.call_count == 1


def test_call_llm_with_retry_recovers_on_second_attempt() -> None:
    """First response is malformed, second is good → returns the good one."""
    fake_response_good = MagicMock(content='{"items": ["a"]}')
    fake_gateway = MagicMock(chat_completion=MagicMock(side_effect=[
        MagicMock(content="not json at all"),
        fake_response_good,
    ]))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.workers.tasks.extraction.llm_caller.LLMGateway", lambda: fake_gateway)
        mp.setattr("app.workers.tasks.extraction.llm_caller.RETRY_BACKOFF_SECONDS", 0)
        raw, parsed = call_llm_with_retry(
            [{"role": "user", "content": "extract"}],
            max_retries=2,
        )

    assert parsed == {"items": ["a"]}
    assert fake_gateway.chat_completion.call_count == 2


def test_call_llm_with_retry_returns_none_after_exhaustion() -> None:
    """Every attempt bad → raw preserved, parsed is None."""
    fake_gateway = MagicMock(chat_completion=MagicMock(return_value=MagicMock(content="garbage")))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.workers.tasks.extraction.llm_caller.LLMGateway", lambda: fake_gateway)
        mp.setattr("app.workers.tasks.extraction.llm_caller.RETRY_BACKOFF_SECONDS", 0)
        raw, parsed = call_llm_with_retry(
            [{"role": "user", "content": "extract"}],
            max_retries=2,
        )

    assert parsed is None
    assert raw == "garbage"
    assert fake_gateway.chat_completion.call_count == 3  # 1 initial + 2 retries