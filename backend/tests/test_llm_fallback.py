"""LLM gateway primary/backup fallback tests (demo-day fuse)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.gateway.llm import LLMGateway


def _resp(content: str, model: str = "m") -> SimpleNamespace:
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        model=model,
        usage=usage,
    )


def _stream_chunks(*deltas: str) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=delta))])
        for delta in deltas
    ]


class FakeCompletions:
    """create() follows a scripted list of outcomes: values succeed, exceptions raise."""

    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _gateway(
    primary_outcomes: list[Any], backup_outcomes: list[Any] | None = None
) -> tuple[LLMGateway, FakeCompletions, FakeCompletions | None]:
    gateway = LLMGateway(
        api_key="primary-key",
        base_url="https://primary",
        model="primary-model",
        backup_api_key="backup-key",
        backup_base_url="https://backup",
        backup_model="backup-model",
    )
    primary = FakeCompletions(primary_outcomes)
    gateway._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=primary.create))
    )
    backup = None
    if backup_outcomes is not None:
        backup = FakeCompletions(backup_outcomes)
        gateway._backup_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=backup.create))
        )
    return gateway, primary, backup


def test_primary_success_never_touches_backup():
    gateway, primary, backup = _gateway(
        [_resp("ok", "primary-model")], [_resp("should-not-be-used", "backup-model")]
    )
    response = gateway.chat_completion([{"role": "user", "content": "hi"}])
    assert response.content == "ok"
    assert response.model == "primary-model"
    assert len(primary.calls) == 1
    assert backup is not None and backup.calls == []


def test_primary_failure_falls_over_to_backup():
    gateway, _, backup = _gateway(
        [RuntimeError("primary down")], [_resp("backup ok", "backup-model")]
    )
    response = gateway.chat_completion(
        [{"role": "user", "content": "hi"}], disable_thinking=True
    )
    assert response.content == "backup ok"
    assert backup is not None
    assert backup.calls[0]["model"] == "backup-model"
    # backup attempt keeps the same payload (incl. thinking extra_body) first
    assert backup.calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_backup_retry_strips_deepseek_extra_body_when_rejected():
    # backup rejects the thinking field once, accepts without it
    gateway, _, backup = _gateway(
        [RuntimeError("primary down")],
        [
            RuntimeError("unknown field thinking"),
            _resp("backup without thinking", "backup-model"),
        ],
    )
    response = gateway.chat_completion(
        [{"role": "user", "content": "hi"}], disable_thinking=True
    )
    assert response.content == "backup without thinking"
    assert backup is not None
    assert "extra_body" in backup.calls[0]
    assert "extra_body" not in backup.calls[1]


def test_failure_without_backup_configured_raises_primary_error():
    gateway = LLMGateway(api_key="k", base_url="u", model="m")  # no backup fields
    assert gateway.backup_enabled is False
    primary = FakeCompletions([RuntimeError("primary down")])
    gateway._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=primary.create))
    )
    try:
        gateway.chat_completion([{"role": "user", "content": "hi"}])
        raise AssertionError("should have raised")
    except RuntimeError as exc:
        assert "primary down" in str(exc)


def test_backup_also_failing_raises_primary_error():
    gateway, _, _ = _gateway(
        [RuntimeError("primary down")],
        [RuntimeError("backup down too"), RuntimeError("backup down too")],
    )
    try:
        gateway.chat_completion(
            [{"role": "user", "content": "hi"}], disable_thinking=True
        )
        raise AssertionError("should have raised")
    except RuntimeError as exc:
        # the primary error is the one worth investigating, so it wins
        assert "primary down" in str(exc)


def test_stream_falls_over_before_first_chunk():
    gateway, primary, backup = _gateway(
        [RuntimeError("primary down")], [_stream_chunks("a", "b", "c")]
    )
    deltas = list(
        gateway.stream_chat_completion([{"role": "user", "content": "hi"}])
    )
    assert deltas == ["a", "b", "c"]
    assert len(primary.calls) == 1
    assert backup is not None and len(backup.calls) == 1
    assert backup.calls[0]["stream"] is True


def test_backup_requires_all_three_fields():
    partial = LLMGateway(
        api_key="k", base_url="u", model="m",
        backup_api_key="bk", backup_base_url="bu",  # missing backup_model
    )
    assert partial.backup_enabled is False
