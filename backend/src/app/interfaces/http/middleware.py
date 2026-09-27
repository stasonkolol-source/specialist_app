"""Контекст запроса (ARCHITECTURE §8.1): X-Request-ID, traceparent, Accept-Language, X-Client,
техработы (флаг `platform.maintenance`).

Чистый ASGI, без BaseHTTPMiddleware: контекст structlog живёт в contextvars задачи
запроса и не теряется. Middleware внешнее для обработчиков ошибок FastAPI, поэтому
ловит всё, что они не отобразили, и отвечает 500 без деталей (RFC 9457, ADR-0020 §9).
"""

import re
import secrets
import time
from collections.abc import Awaitable, Callable

import sentry_sdk
import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.interfaces.http.client import ClientInfo, ClientPolicy, format_version, negotiate_locale
from app.interfaces.http.errors import INTERNAL_ERROR, Problems
from app.platform.kernel.ids import new_id
from app.platform.kernel.localized import Locale
from app.platform.observability.logging import bind_context, clear_context

log = structlog.get_logger(__name__)

_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
_TRACEPARENT = re.compile(r"[0-9a-f]{2}-(?P<trace_id>[0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}")
QUIET_PATHS = frozenset({"/up"})
"""Без access-лога: healthcheck прокси дёргает их каждые несколько секунд."""

INVALID_CLIENT_HEADER = "invalid_client_header"
CLIENT_UPGRADE_REQUIRED = "client_upgrade_required"
MAINTENANCE = "maintenance"
MAINTENANCE_RETRY_AFTER = 120
"""Секунды до повтора при техработах: клиент показывает экран S49 и не долбит сервер."""
MAINTENANCE_EXEMPT = ("/client-config", "/openapi.json", "/docs")
"""Пути под /api/v1, которые работают и в техработы: по client-config клиент узнаёт о них сам."""


def request_id_from(header: str | None) -> str:
    """Пришедший X-Request-ID, если он безопасен для логов, иначе новый."""
    if header and _REQUEST_ID.fullmatch(header):
        return header
    return new_id().hex


def trace_id_from(header: str | None) -> str:
    """trace-id из W3C traceparent; нет или битый — новый случайный."""
    if header and (match := _TRACEPARENT.fullmatch(header.strip())):
        trace_id = match["trace_id"]
        if trace_id != "0" * 32:
            return trace_id
    return secrets.token_hex(16)


class RequestContextMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        problems: Problems,
        clients: Callable[[], Awaitable[ClientPolicy]],
        api_prefix: str,
        maintenance: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self.app = app
        self.problems = problems
        self.clients = clients
        self.api_prefix = api_prefix
        self.maintenance = maintenance

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        request_id = request_id_from(headers.get("x-request-id"))
        trace_id = trace_id_from(headers.get("traceparent"))
        state = scope.setdefault("state", {})
        state.update(
            request_id=request_id,
            trace_id=trace_id,
            locale=negotiate_locale(headers.get("accept-language")),
        )
        bind_context(request_id=request_id, trace_id=trace_id)
        sentry_sdk.set_tag("trace_id", trace_id)

        status = 500
        started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status, started
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        begin = time.perf_counter()
        try:
            rejection = await self._check_client(
                scope, headers, trace_id, state["locale"]
            ) or await self._check_maintenance(scope, trace_id, state["locale"])
            if rejection is not None:
                await rejection(scope, receive, send_with_id)
                return
            await self.app(scope, receive, send_with_id)
        except Exception:
            sentry_sdk.capture_exception()
            log.exception("http_unhandled_error", method=scope["method"], path=scope["path"])
            if started:
                raise
            response = self.problems.response(
                500, INTERNAL_ERROR, trace_id=trace_id, locale=state["locale"]
            )
            await response(scope, receive, send_with_id)
        finally:
            if scope["path"] not in QUIET_PATHS:
                log.info(
                    "http_request",
                    method=scope["method"],
                    path=scope["path"],
                    status=status,
                    duration_ms=round((time.perf_counter() - begin) * 1000, 1),
                )
            clear_context()

    async def _check_client(
        self, scope: Scope, headers: Headers, trace_id: str, locale: Locale
    ) -> ASGIApp | None:
        """X-Client на /api: битый заголовок — 400, устаревший клиент — 426."""
        if not scope["path"].startswith(self.api_prefix):
            return None
        raw = headers.get("x-client")
        if raw is None:
            return None
        client = ClientInfo.parse(raw)
        if client is None:
            return self.problems.response(
                400, INVALID_CLIENT_HEADER, trace_id=trace_id, locale=locale
            )
        scope["state"]["client"] = client
        minimum = (await self.clients()).required_upgrade(client)
        if minimum is None:
            return None
        return self.problems.response(
            426,
            CLIENT_UPGRADE_REQUIRED,
            trace_id=trace_id,
            locale=locale,
            platform=client.platform,
            min_version=format_version(minimum),
        )

    async def _check_maintenance(
        self, scope: Scope, trace_id: str, locale: Locale
    ) -> ASGIApp | None:
        """Флаг `platform.maintenance` включён — 503 `maintenance` на /api, кроме client-config:
        по нему Mini App показывает экран техработ (S49) и правовые тексты (S48)."""
        path: str = scope["path"]
        if self.maintenance is None or not path.startswith(self.api_prefix):
            return None
        if path.removeprefix(self.api_prefix).startswith(MAINTENANCE_EXEMPT):
            return None
        if not await self.maintenance():
            return None
        return self.problems.response(
            503,
            MAINTENANCE,
            trace_id=trace_id,
            locale=locale,
            headers={"Retry-After": str(MAINTENANCE_RETRY_AFTER)},
        )
