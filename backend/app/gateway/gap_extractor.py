"""Ollama adapter dedicated to the fine-tuned Schema 3.0 extractor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings
from app.domains.gap.prompt import TRAINING_INSTRUCTION, repair_prompt
from app.domains.gap.schemas import GapAnnotationOutput
from app.domains.gap.validation import parse_model_json, validate_annotation


@dataclass
class GapExtractionResult:
    output: GapAnnotationOutput | None
    attempts: int
    raw_responses: list[str] = field(default_factory=list)
    api_responses: list[dict[str, Any]] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)


class OllamaGapExtractor:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or settings.gap_extractor_base_url).rstrip("/")
        self.model = model or settings.gap_extractor_model
        self.client = client or httpx.Client(timeout=settings.gap_extractor_timeout_seconds)

    @property
    def model_parameters(self) -> dict[str, Any]:
        return {
            "num_ctx": settings.gap_extractor_num_ctx,
            "num_predict": settings.gap_extractor_num_predict,
            "temperature": settings.gap_extractor_temperature,
            "top_p": settings.gap_extractor_top_p,
            "repeat_penalty": settings.gap_extractor_repeat_penalty,
            "seed": settings.gap_extractor_seed,
        }

    def _call(self, messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
        response = self.client.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "messages": messages,
                "options": self.model_parameters,
            },
        )
        response.raise_for_status()
        payload = response.json()
        content = str((payload.get("message") or {}).get("content") or "")
        if not content.strip():
            raise RuntimeError("Ollama returned an empty assistant message")
        return content, payload

    def extract(
        self,
        markdown: str,
        *,
        instruction: str = TRAINING_INSTRUCTION,
        repair_attempts: int | None = None,
    ) -> GapExtractionResult:
        maximum_repairs = (
            settings.gap_extractor_repair_attempts
            if repair_attempts is None
            else max(0, repair_attempts)
        )
        messages = [{"role": "user", "content": f"{instruction.strip()}\n\n{markdown.strip()}"}]
        raw_responses: list[str] = []
        api_responses: list[dict[str, Any]] = []
        errors: list[str] = []

        for attempt in range(1, maximum_repairs + 2):
            raw, api_response = self._call(messages)
            raw_responses.append(raw)
            api_responses.append(api_response)
            try:
                parsed = parse_model_json(raw)
                output, errors = validate_annotation(parsed)
            except ValueError as exc:
                output = None
                errors = [str(exc)]
            if output is not None:
                return GapExtractionResult(output, attempt, raw_responses, api_responses, [])
            if attempt <= maximum_repairs:
                messages.extend(
                    [
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content": repair_prompt(errors)},
                    ]
                )
        return GapExtractionResult(None, len(raw_responses), raw_responses, api_responses, errors)

