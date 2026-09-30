"""Moderation на OpenAI omni-moderation (ADR-0016 §3: бесплатно, текст и изображения).

`POST /v1/moderations` через `httpx.AsyncClient` из DI (таймаут — `AI_TIMEOUT_SECONDS`: проверка
стоит на пути публикации). Любой сбой (сеть, таймаут, 429, 5xx, неожиданный ответ, 401 от
неверного ключа) — `unavailable` и сбой предохранителя: контент уйдёт в ручную очередь.
Текст — без контактов (contact_masking): провайдеру они не нужны.
"""

from typing import Any

import httpx
import structlog

from app.platform.ai.breaker import CircuitBreaker
from app.platform.ai.port import ModerationResult
from app.platform.text.contact_masking import mask_contacts

log = structlog.get_logger(__name__)

URL = "https://api.openai.com/v1/moderations"


class OpenAiModeration:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: str,
        model: str,
        breaker: CircuitBreaker,
    ) -> None:
        self._http, self._api_key, self._model, self._breaker = http, api_key, model, breaker

    async def check_text(self, text: str) -> ModerationResult:
        return await self._check(mask_contacts(text))

    async def check_image(self, url: str) -> ModerationResult:
        return await self._check([{"type": "image_url", "image_url": {"url": url}}])

    async def _check(self, content: str | list[dict[str, Any]]) -> ModerationResult:
        if not self._breaker.allow():
            return ModerationResult.unavailable()
        try:
            response = await self._http.post(
                URL,
                json={"model": self._model, "input": content},
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        except httpx.HTTPError as exc:
            return self._failed(error=type(exc).__name__)
        if response.status_code != httpx.codes.OK:
            return self._failed(status=response.status_code)
        try:
            [result, *_] = response.json()["results"]
            scores = {str(k): float(v) for k, v in result["category_scores"].items()}
            flagged = bool(result["flagged"])
        except (KeyError, TypeError, ValueError) as exc:
            return self._failed(error=type(exc).__name__)
        self._breaker.success()
        return ModerationResult(flagged=flagged, scores=scores)

    def _failed(self, **details: object) -> ModerationResult:
        self._breaker.failure()
        log.warning("ai_moderation_unavailable", breaker_open=self._breaker.open, **details)
        return ModerationResult.unavailable()
