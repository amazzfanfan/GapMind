"""LLM Gateway - Deepseek integration.

Phase 0: skeleton with a minimal `chat_completion` method. Phase 2-3 will add
structured-output extraction, retry, and token/cost tracking.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generator

from openai import OpenAI

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class LLMResponse:
    """Normalized LLM response."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    raw: Any = None


class LLMGateway:
    """Thin wrapper over Deepseek's OpenAI-compatible API.

    Uses the `openai` SDK with a custom base_url. Phase 0 only implements the
    basic chat completion; structured extraction and cost tracking come later.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.deepseek_api_key
        self.base_url = base_url if base_url is not None else settings.deepseek_base_url
        self.model = model if model is not None else settings.deepseek_model
        self._client: OpenAI | None = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            if not self.api_key:
                raise RuntimeError(
                    "DEEPSEEK_API_KEY is not set. Configure backend/.env."
                )
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
        disable_thinking: bool = False,
    ) -> LLMResponse:
        """Run a chat completion against the configured Deepseek model.

        ``disable_thinking=True`` turns off the model's chain-of-thought
        (``thinking.type = "disabled"``). Reasoning models (deepseek-v4-flash)
        otherwise spend the whole ``max_tokens`` budget on reasoning and
        return an empty ``content`` for long structured-extraction prompts
        (see docs/knowledge_dedup_fix_plan.md §八). Structured JSON callers
        (extraction / discover synthesis / judge) should pass it; free-form
        chat may keep thinking enabled.

        NOTE: do NOT combine ``thinking.type="disabled"`` with a
        ``reasoning_effort`` param — Deepseek returns a 400 on that conflict.
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if response_format is not None:
            kwargs["response_format"] = response_format
        if disable_thinking:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        logger.info("llm.chat.start", model=self.model, messages=len(messages))
        resp = self.client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        usage = resp.usage
        return LLMResponse(
            content=choice.message.content or "",
            model=resp.model,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            total_tokens=getattr(usage, "total_tokens", 0) if usage else 0,
            raw=resp,
        )


    def stream_chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        disable_thinking: bool = False,
    ) -> Generator[str, None, None]:
        """Yield text deltas from a streaming chat completion (P0.5-1).

        Mirror of ``chat_completion`` but with ``stream=True``; each yielded
        string is one content delta. Structured-format callers should keep
        using the non-streaming version.
        """
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if disable_thinking:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        stream = self.client.chat.completions.create(**kwargs, stream=True)
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    def ping(self) -> bool:
        """Lightweight connectivity check - returns True if API key is set.

        A real network ping is deferred to Phase 2 to avoid spamming the API
        during health checks.
        """
        return bool(self.api_key)


_gateway: LLMGateway | None = None


def get_llm_gateway() -> LLMGateway:
    """Singleton accessor for the LLM gateway."""
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
