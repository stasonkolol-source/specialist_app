"""Idempotency-Key для создающих POST (ADR-0003, ADR-0020 §4, ARCHITECTURE §8.1).

    creating = idempotent_router()          # маршруты этого роутера требуют ключ
    @creating.post("/jobs") …
    router.include_router(creating)

Три последовательных блока UoW в одном скоупе запроса:
1. `reserve()` до use case: новый ключ — занять; готовый ответ — отдать повторно
   (`Idempotency-Replayed: true`); ключ в работе — 409; другое тело — 422;
2. обработчик и его use case со своим `async with uow`;
3. `complete()` с кодом и телом ответа; ошибка — `release()`, повтор выполнится заново.
Ответ хранится 24 ч, потом ключ удаляет `platform.idempotency_cleanup`.
"""

import hashlib
import json
import re
from collections.abc import Callable, Coroutine
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.platform.db.port import UnitOfWork
from app.platform.idempotency.errors import (
    IdempotencyInProgressError,
    IdempotencyKeyRequiredError,
    IdempotencyKeyReusedError,
    InvalidIdempotencyKeyError,
)
from app.platform.idempotency.port import IdempotencyStore, ReservationStatus
from app.platform.kernel.clock import Clock
from app.platform.kernel.principal import Principal

HEADER = "Idempotency-Key"
TTL = timedelta(hours=24)
_KEY = re.compile(r"[A-Za-z0-9._:-]{8,255}")

Handler = Callable[[Request], Coroutine[Any, Any, Response]]


def parse_key(raw: str | None) -> str:
    if raw is None:
        raise IdempotencyKeyRequiredError(header=HEADER)
    if not _KEY.fullmatch(raw):
        raise InvalidIdempotencyKeyError(header=HEADER)
    return raw


def request_hash(request: Request, body: bytes) -> bytes:
    head = f"{request.method} {request.url.path}?{request.url.query}\n".encode()
    return hashlib.sha256(head + body).digest()


class IdempotentRoute(APIRoute):
    """Маршрут, у которого ключ обязателен и ответ повторяется (описан в OpenAPI)."""

    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any) -> None:
        extra = dict(kwargs.pop("openapi_extra", None) or {})
        extra["parameters"] = [
            *extra.get("parameters", []),
            {
                "name": HEADER,
                "in": "header",
                "required": True,
                "description": "Ключ операции: повтор с тем же ключом вернёт тот же ответ",
                "schema": {"type": "string", "minLength": 8, "maxLength": 255},
            },
        ]
        super().__init__(path, endpoint, openapi_extra=extra, **kwargs)

    def get_route_handler(self) -> Handler:
        handler = super().get_route_handler()

        async def idempotent(request: Request) -> Response:
            container = request.state.dishka_container
            principal = await container.get(Principal)  # 401 раньше ошибок ключа
            key = parse_key(request.headers.get(HEADER))
            uow = await container.get(UnitOfWork)
            store = await container.get(IdempotencyStore)
            clock = await container.get(Clock)
            digest = request_hash(request, await request.body())
            async with uow:
                reservation = await store.reserve(
                    principal.user_id, key, digest, not_before=clock.now() - TTL
                )
            match reservation.status:
                case ReservationStatus.COMPLETED:
                    return _replay(reservation.status_code or 200, reservation.response)
                case ReservationStatus.IN_PROGRESS:
                    raise IdempotencyInProgressError
                case ReservationStatus.MISMATCH:
                    raise IdempotencyKeyReusedError(header=HEADER)
                case ReservationStatus.RESERVED:
                    pass
            try:
                response = await handler(request)
            except BaseException:
                async with uow:
                    await store.release(principal.user_id, key)
                raise
            async with uow:
                if response.status_code >= 400:
                    await store.release(principal.user_id, key)
                else:
                    body = bytes(response.body)
                    await store.complete(
                        principal.user_id,
                        key,
                        response.status_code,
                        json.loads(body) if body else None,
                    )
            return response

        return idempotent


def _replay(status_code: int, body: object) -> Response:
    headers = {"Idempotency-Replayed": "true"}
    if body is None:
        return Response(status_code=status_code, headers=headers)
    return JSONResponse(body, status_code=status_code, headers=headers)


def idempotent_router(**kwargs: Any) -> APIRouter:
    """Роутер создающих POST: у каждого маршрута обязателен Idempotency-Key."""
    return APIRouter(route_class=IdempotentRoute, **kwargs)
