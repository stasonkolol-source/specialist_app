"""Адаптер PostHog EU (DEVELOPMENT_PLAN 1.7, K32): capture API, одно событие — один запрос.

- `distinct_id` — внутренний UUID пользователя; device ID не отправляем.
- `$geoip_disable`: PostHog не определяет место по IP — запрос идёт с сервера, а не с
  телефона, и такой «город» только испортил бы данные.
- `uuid` события детерминирован (events.analytics_event): повтор задачи PostHog склеит.
- Событие удалённого аккаунта не уходит (deleted.py): иначе PostHog заново завёл бы персону,
  удалённую по UserDeleted (2.12b).
- 5xx, 408 и сетевые ошибки — ExternalServiceError (задача повторит), 429 —
  RateLimitedError с Retry-After. Остальное, кроме 2xx (неверный ключ, битое событие,
  редирект с неверного адреса), повтором не лечится: ошибка в лог и Sentry, а не молчаливая
  «доставка» и не бесконечные повторы.
"""

from typing import Final

import httpx
import sentry_sdk
import structlog
from pydantic import SecretStr

from app.platform.analytics.deleted import skip_deleted
from app.platform.analytics.events import ensure_allowed
from app.platform.analytics.port import AnalyticsEvent, DeletedUsers
from app.platform.kernel.errors import ExternalServiceError, RateLimitedError

log = structlog.get_logger(__name__)

CAPTURE_PATH: Final = "/i/v0/e/"
LIBRARY: Final = "sosedi-backend"
DEFAULT_RETRY_AFTER: Final = 60


class PostHogAnalytics:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        api_key: SecretStr,
        host: str,
        environment: str,
        deleted: DeletedUsers | None = None,
    ) -> None:
        self._client = client
        self._api_key = api_key
        self._url = host.rstrip("/") + CAPTURE_PATH
        self._environment = environment
        self._deleted = deleted

    async def capture(self, event: AnalyticsEvent) -> None:
        ensure_allowed(event)
        if await skip_deleted(self._deleted, event):
            return
        payload = {
            "api_key": self._api_key.get_secret_value(),
            "event": event.name,
            "distinct_id": str(event.distinct_id),
            "uuid": str(event.event_id),
            "timestamp": event.occurred_at.isoformat(),
            "properties": {
                **event.properties,
                "environment": self._environment,
                "$lib": LIBRARY,
                "$geoip_disable": True,
            },
        }
        try:
            response = await self._client.post(self._url, json=payload)
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
            sentry_sdk.capture_message(f"posthog rejected event {event.name}", level="error")
            log.error("analytics_rejected", name=event.name, status=response.status_code)


def retry_after(response: httpx.Response) -> int:
    try:
        return max(1, int(response.headers.get("Retry-After", DEFAULT_RETRY_AFTER)))
    except ValueError:
        return DEFAULT_RETRY_AFTER
