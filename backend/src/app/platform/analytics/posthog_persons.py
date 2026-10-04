"""Удаление персоны в PostHog по UserDeleted (DEVELOPMENT_PLAN 2.12b, K32a; ARCHITECTURE §7.10).

`POST /api/projects/<id>/persons/bulk_delete/` с `distinct_ids` и `delete_events`: персону по
distinct_id (внутренний UUID, как у capture) PostHog находит и удаляет сам, одним запросом, и
ключу нужен только scope `person:write`. `DELETE /persons/<uuid>/` PostHog убрал из схемы API в
пользу bulk_delete, а поиск персоны перед ним требовал бы ещё и `person:read`. Ответ 202:
персона и её distinct_id удаляются в фоне за минуты, события — отложенной задачей PostHog
(пакетом, раз в неделю) и только пойманные до запроса — поэтому capture для удалённых уже молчит
(deleted.py).

Повтор безопасен: персоны нет (`persons_found` 0 — удалена раньше или событий не было) — готово;
повторную постановку удаления событий PostHog не дублирует. Ошибки — как у capture (posthog.py):
5xx, 408 и сеть — ExternalServiceError, 429 — RateLimitedError с Retry-After, задача повторит.
202 с непустым `deletion_errors` — PostHog не удалил часть (персону или постановку событий):
это не «готово», а ExternalServiceError — повтор. Повторы задачи ограничены (tasks.py,
FORGET_RETRY), после них она падает в failed с ERROR-логом Procrastinate — Sentry.
Остальное (ключ без scope — 401/403, неверный id проекта — 404) повтором не лечится, но и молча
считать персону удалённой нельзя: PostHogPersonsError — Sentry, задача упадёт и останется в
очереди failed; после исправления ключа её перезапускают (runbook deletion-request.md).
"""

from typing import Final
from uuid import UUID

import httpx
import structlog

from app.platform.analytics.posthog import retry_after
from app.platform.kernel.errors import ExternalServiceError, RateLimitedError

log = structlog.get_logger(__name__)

BULK_DELETE_PATH: Final = "persons/bulk_delete/"
MISSING_KEYS: Final = (
    "ANALYTICS_POSTHOG_PERSONAL_API_KEY or ANALYTICS_POSTHOG_PROJECT_ID is not set"
)


class PostHogPersonsError(RuntimeError):
    """PostHog отказал в удалении: ключ без scope `person:write`, чужой или неверный проект."""


class PostHogPersons:
    """`client` — с base_url `…/api/projects/<id>/` и personal API key (`client_for`)."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def forget(self, user_id: UUID) -> None:
        body = {"distinct_ids": [str(user_id)], "delete_events": True}
        try:
            response = await self._client.post(BULK_DELETE_PATH, json=body)
        except httpx.HTTPError as exc:
            raise ExternalServiceError(service="posthog", reason=type(exc).__name__) from exc
        if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
            raise RateLimitedError(retry_after=retry_after(response))
        if (
            response.status_code >= httpx.codes.INTERNAL_SERVER_ERROR
            or response.status_code == httpx.codes.REQUEST_TIMEOUT
        ):
            raise ExternalServiceError(service="posthog", status=response.status_code)
        if not response.is_success:
            raise PostHogPersonsError(f"posthog bulk_delete: HTTP {response.status_code}")
        payload = _payload(response)
        found = payload.get("persons_found")
        errors = payload.get("deletion_errors")
        if isinstance(errors, list) and errors:
            # содержимое ошибок не пишем: в нём бывают distinct_id и данные персоны
            log.warning(
                "analytics_person_deletion_incomplete", user_id=str(user_id), errors=len(errors)
            )
            raise ExternalServiceError(service="posthog", reason="deletion_errors")
        # id — внутренний UUID, тот же, что в логах задач; по нему поддержка находит запись
        log.info(
            "analytics_person_forgotten",
            user_id=str(user_id),
            persons_found=found if isinstance(found, int) else None,
        )


class NoPersonDeletion:
    """Без personal API key или id проекта (K32a) удалить персону нечем. Если события в PostHog
    уходят (`capturing`), это пропуск удаления — предупреждение в лог воркера; без PostHog
    (dev, тесты) удалять нечего."""

    def __init__(self, *, capturing: bool) -> None:
        self._capturing = capturing

    async def forget(self, user_id: UUID) -> None:
        if self._capturing:
            log.warning(
                "analytics_person_not_forgotten",
                user_id=str(user_id),
                reason=MISSING_KEYS,
            )
        else:
            log.info("analytics_person_not_forgotten", user_id=str(user_id), reason="no_posthog")


def _payload(response: httpx.Response) -> dict[str, object]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}
