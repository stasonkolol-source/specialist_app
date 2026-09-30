"""Moderation на OpenAI omni-moderation (ADR-0016 §3: бесплатно, текст и изображения).

`POST /v1/moderations` через `httpx.AsyncClient` из DI. Вся проверка укладывается в `deadline`
секунд (`AI_TIMEOUT_SECONDS`): она стоит на пути публикации. Текст — без контактов
(contact_masking) и не длиннее MAX_CHARS.

Исходы (всё, кроме вердикта, — `Unavailable`, контент уйдёт в ручную очередь):
- сбой провайдера — сеть, таймаут, 429, 5xx, 401, 404, неожиданный ответ — сбой
  предохранителя;
- провайдер не принял именно этот запрос (400, 413, 422: изображение не скачалось, текст
  слишком большой) — без сбоя: другие проверки это не остановит.
У текста и изображений свои предохранители: пять изображений, которые провайдер не смог
скачать, не выключат проверку текста.
"""

import asyncio
from typing import Any

import httpx
import structlog

from app.platform.ai.breaker import CircuitBreaker
from app.platform.ai.port import ModerationResult, Unavailable, UnavailableReason
from app.platform.text.contact_masking import mask_contacts

log = structlog.get_logger(__name__)

URL = "https://api.openai.com/v1/moderations"
MAX_CHARS = 10_000
REJECTED = frozenset({400, 413, 422})
"""Ответы про сам запрос, а не про провайдера."""


class OpenAiModeration:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: str,
        model: str,
        text_breaker: CircuitBreaker,
        image_breaker: CircuitBreaker,
        deadline: float,
    ) -> None:
        self._http, self._api_key, self._model = http, api_key, model
        self._text_breaker, self._image_breaker = text_breaker, image_breaker
        self._deadline = deadline

    async def check_text(self, text: str) -> ModerationResult | Unavailable:
        content = mask_contacts(text[: MAX_CHARS * 2])[:MAX_CHARS]
        return await self._check(content, self._text_breaker)

    async def check_image(self, url: str) -> ModerationResult | Unavailable:
        content = [{"type": "image_url", "image_url": {"url": url}}]
        return await self._check(content, self._image_breaker)

    async def _check(
        self, content: str | list[dict[str, Any]], breaker: CircuitBreaker
    ) -> ModerationResult | Unavailable:
        if not breaker.allow():
            return Unavailable(UnavailableReason.BREAKER_OPEN)
        try:
            async with asyncio.timeout(self._deadline):
                response = await self._http.post(
                    URL,
                    json={"model": self._model, "input": content},
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except (httpx.HTTPError, TimeoutError) as exc:
            return _failed(breaker, error=type(exc).__name__)
        except Exception as exc:  # недоступность — вердикт, а не исключение (port.py)
            log.exception("ai_moderation_unexpected")
            return _failed(breaker, error=type(exc).__name__)
        if response.status_code in REJECTED:
            log.info("ai_moderation_rejected_input", status=response.status_code)
            return Unavailable(UnavailableReason.REJECTED_INPUT)
        if response.status_code != httpx.codes.OK:
            return _failed(breaker, status=response.status_code)
        result = _parse(response)
        if result is None:
            return _failed(breaker, error="unexpected_body")
        breaker.success()
        return result


def _parse(response: httpx.Response) -> ModerationResult | None:
    try:
        [result, *_] = response.json()["results"]
        raw_scores = result["category_scores"]
        flagged = result["flagged"]
        if not isinstance(raw_scores, dict) or not isinstance(flagged, bool):
            return None
        scores = {str(k): float(v) for k, v in raw_scores.items()}
    except KeyError, TypeError, ValueError:
        return None
    return ModerationResult(flagged=flagged, scores=scores)


def _failed(breaker: CircuitBreaker, **details: object) -> Unavailable:
    breaker.failure()
    log.warning("ai_moderation_unavailable", breaker_open=breaker.open, **details)
    return Unavailable(UnavailableReason.PROVIDER_ERROR)
