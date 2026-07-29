"""Judgement gateway unit tests."""

from __future__ import annotations

from types import SimpleNamespace

from app.gateway.judge import JudgementGateway


def _gateway_with_response(content: str, finish_reason: str = "stop"):
    calls: list[dict] = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                    finish_reason=finish_reason,
                )
            ]
        )

    gateway = JudgementGateway(api_key="test")
    gateway._client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=create),
        )
    )
    return gateway, calls


def test_batch_judgement_reserves_tokens_for_reasoning_model() -> None:
    content = (
        "["
        + ",".join(
            f'{{"index":{index},"judgement":"overlaps","confidence":0.5}}'
            for index in range(8)
        )
        + "]"
    )
    gateway, calls = _gateway_with_response(content)

    result = gateway.judge_batch("claim", ["passage"] * 8)

    assert result.error is None
    assert len(result.hits) == 8
    assert calls[0]["max_tokens"] == 2048


def test_empty_judgement_response_is_reported_as_error() -> None:
    gateway, _ = _gateway_with_response("", finish_reason="length")

    result = gateway.judge_batch("claim", ["passage"])

    assert result.error is not None
    assert "empty content" in result.error
    assert result.hits[0].judgement == "unknown"
    assert result.hits[0].confidence == 0.0
