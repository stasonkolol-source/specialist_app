"""Ошибки HTTP в формате RFC 9457 (ADR-0020 §9, ARCHITECTURE §8.3).

Единственное место, где исключение превращается в ответ: доменные ошибки — по базовому
классу из platform/kernel/errors.py, ошибки запроса FastAPI и Starlette — по статусу.
Прочие исключения ловит RequestContextMiddleware и отвечает 500 без деталей.

Поля ответа сверх RFC 9457: у `RestrictedError` — `restriction` и `until`, у любой доменной
ошибки — её `public_params` (`documents` у 403 `consent_required`, …).

`detail` и `errors[].message` — на языке `Accept-Language` из каталогов gettext (шаг 1.2):
ключи `errors.<code>` и `validation.<тип ошибки pydantic>`; нет ключа — текст pydantic.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC
from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.interfaces.http.client import DEFAULT_LOCALE
from app.platform.i18n.translator import Translator
from app.platform.kernel.errors import (
    ConflictError,
    DomainError,
    DomainValidationError,
    ExternalServiceError,
    ForbiddenError,
    NotAuthenticatedError,
    NotFoundError,
    RateLimitedError,
    RestrictedError,
    StaleVersionError,
)
from app.platform.kernel.localized import Locale

log = structlog.get_logger(__name__)

PROBLEM_JSON = "application/problem+json"

DOMAIN_STATUS: tuple[tuple[type[DomainError], HTTPStatus], ...] = (
    (NotAuthenticatedError, HTTPStatus.UNAUTHORIZED),
    (NotFoundError, HTTPStatus.NOT_FOUND),
    (ForbiddenError, HTTPStatus.FORBIDDEN),
    (ConflictError, HTTPStatus.CONFLICT),
    (StaleVersionError, HTTPStatus.PRECONDITION_FAILED),
    (DomainValidationError, HTTPStatus.UNPROCESSABLE_CONTENT),
    (RateLimitedError, HTTPStatus.TOO_MANY_REQUESTS),
    (ExternalServiceError, HTTPStatus.SERVICE_UNAVAILABLE),
)
"""Таблица ADR-0020 §9. Порядок важен: подкласс — раньше базового (Restricted ⊂ Forbidden)."""

HTTP_CODES: Mapping[int, str] = {
    400: "bad_request",
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    406: "not_acceptable",
    413: "payload_too_large",
    415: "unsupported_media_type",
}
"""Коды ошибок, которые Starlette поднимает сама (нет маршрута, не тот метод, …)."""

HTTP_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
INTERNAL_ERROR = "internal_error"
VALIDATION_ERROR = "validation_error"
MALFORMED_REQUEST = "malformed_request"


def status_for(error_type: type[DomainError]) -> HTTPStatus | None:
    """HTTP-статус класса доменной ошибки; None — класс вне таблицы, это ошибка программиста."""
    for base, status in DOMAIN_STATUS:
        if issubclass(error_type, base):
            return status
    return None


@dataclass(frozen=True, slots=True)
class FieldError:
    field: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class Problems:
    """Фабрика ответов RFC 9457: одна на приложение, её же использует middleware.

    `detail` — текст ключа `errors.<code>` на языке запроса (ADR-0013); параметры шаблона —
    именованные параметры ошибки (`retry_after`, …).
    """

    base_url: str
    translator: Translator | None = None

    def text(
        self, key: str, locale: Locale, params: Mapping[str, object] | None = None
    ) -> str | None:
        return self.translator.text(key, locale, **(params or {})) if self.translator else None

    def response(
        self,
        status: int,
        code: str,
        *,
        trace_id: str | None,
        locale: Locale = DEFAULT_LOCALE,
        params: Mapping[str, object] | None = None,
        errors: Sequence[FieldError] = (),
        headers: Mapping[str, str] | None = None,
        **extensions: Any,
    ) -> JSONResponse:
        detail = self.text(f"errors.{code}", locale, params)
        body: dict[str, Any] = {
            "type": f"{self.base_url.rstrip('/')}/problems/{code.replace('_', '-')}",
            "title": HTTPStatus(status).phrase,
            "status": int(status),
            "code": code,
        }
        if detail is not None:
            body["detail"] = detail
        if errors:
            body["errors"] = [
                {"field": e.field, "code": e.code, "message": e.message} for e in errors
            ]
        body.update(extensions)
        body["trace_id"] = trace_id
        return JSONResponse(body, status_code=int(status), headers=headers, media_type=PROBLEM_JSON)


def trace_id_of(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def locale_of(request: Request) -> Locale:
    locale = getattr(request.state, "locale", None)
    return locale if isinstance(locale, Locale) else DEFAULT_LOCALE


def install_error_handlers(app: FastAPI, problems: Problems) -> None:
    """Подключить отображение ошибок к приложению FastAPI."""

    async def domain_error(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, DomainError)  # noqa: S101 — FastAPI передаёт Exception
        status = status_for(type(exc))
        if status is None:
            raise exc  # DomainError вне таблицы §9 — 500 в middleware
        trace_id = trace_id_of(request)
        headers: dict[str, str] = {}
        extensions: dict[str, Any] = {
            name: exc.params[name] for name in exc.public_params if name in exc.params
        }
        match exc:
            case NotAuthenticatedError():
                headers["WWW-Authenticate"] = "Bearer"
            case RestrictedError(restriction=restriction, until=until):
                extensions["restriction"] = restriction
                extensions["until"] = (
                    until.astimezone(UTC).isoformat().replace("+00:00", "Z") if until else None
                )
            case RateLimitedError(retry_after=retry_after, limit=limit):
                headers["Retry-After"] = str(retry_after)
                headers["RateLimit-Remaining"] = "0"
                headers["RateLimit-Reset"] = str(retry_after)
                if limit is not None:
                    headers["RateLimit-Limit"] = str(limit)
            case ExternalServiceError():
                log.warning("external_service_unavailable", code=exc.code)
            case _:
                pass
        return problems.response(
            status,
            exc.code,
            trace_id=trace_id,
            locale=locale_of(request),
            params=exc.params,
            headers=headers,
            **extensions,
        )

    async def request_validation(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, RequestValidationError)  # noqa: S101
        raw = list(exc.errors())
        locale = locale_of(request)
        if raw and all(e.get("type") == "json_invalid" for e in raw):
            return problems.response(
                400, MALFORMED_REQUEST, trace_id=trace_id_of(request), locale=locale
            )
        errors = [
            FieldError(
                field=_field(e.get("loc", ())),
                code=str(e["type"]),
                message=problems.text(f"validation.{e['type']}", locale, e.get("ctx"))
                or str(e["msg"]),
            )
            for e in raw
        ]
        return problems.response(
            422, VALIDATION_ERROR, trace_id=trace_id_of(request), locale=locale, errors=errors
        )

    async def http_error(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, StarletteHTTPException)  # noqa: S101
        code = HTTP_CODES.get(exc.status_code, f"http_{exc.status_code}")
        headers = dict(exc.headers or {})
        if exc.status_code == HTTPStatus.METHOD_NOT_ALLOWED:
            headers["Allow"] = allowed_methods(request) or headers.get("Allow", "")
        return problems.response(
            exc.status_code,
            code,
            trace_id=trace_id_of(request),
            locale=locale_of(request),
            headers=headers,
        )

    app.add_exception_handler(DomainError, domain_error)
    app.add_exception_handler(RequestValidationError, request_validation)
    app.add_exception_handler(StarletteHTTPException, http_error)


def allowed_methods(request: Request) -> str | None:
    """Все методы пути для `Allow`. Starlette перечисляет только методы первого совпавшего
    маршрута (GET /me без PATCH /me), поэтому берём их из схемы OpenAPI приложения."""
    for pattern, methods in _method_table(request.app):
        if pattern.fullmatch(request.url.path):
            return ", ".join(sorted(methods))
    return None


def _method_table(app: FastAPI) -> list[tuple[re.Pattern[str], frozenset[str]]]:
    table: list[tuple[re.Pattern[str], frozenset[str]]] | None = getattr(
        app.state, "allow_table", None
    )
    if table is None:
        table = []
        for path, item in app.openapi().get("paths", {}).items():
            methods = {method.upper() for method in item if method.upper() in HTTP_METHODS}
            if "GET" in methods:
                methods.add("HEAD")
            regex = re.sub(r"\\\{[^}]*\\\}", "[^/]+", re.escape(path))
            table.append((re.compile(regex), frozenset(methods)))
        app.state.allow_table = table
    return table


def _field(loc: Sequence[int | str]) -> str:
    """`("body", "budget", "max")` → `budget.max`; для query и path место остаётся в имени."""
    parts = list(loc[1:] if loc and loc[0] == "body" else loc)
    return ".".join(str(part) for part in parts)
