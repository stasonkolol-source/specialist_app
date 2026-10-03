"""HTTP-каркас: RFC 9457, middleware, `/up` (DEVELOPMENT_PLAN 0.13a, ADR-0020 §9).

Настройки указывают на адреса, где никто не слушает: каркас не должен ходить в БД.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from dishka.integrations.fastapi import FromDishka, inject
from pydantic import BaseModel
from structlog.testing import capture_logs

from app.platform.kernel.errors import (
    ConcurrentModificationError,
    ConflictError,
    DomainError,
    DomainValidationError,
    ExternalServiceError,
    ForbiddenError,
    NotAuthenticatedError,
    NotFoundError,
    ProgrammingError,
    RateLimitedError,
    RestrictedError,
    StaleVersionError,
)
from app.platform.kernel.localized import Locale
from app.platform.settings import Settings
from tests.plugins.http import http_client, sample_router

pytestmark = pytest.mark.unit

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
TRACEPARENT = f"00-{TRACE_ID}-00f067aa0ba902b7-01"


class OrphanError(DomainError):
    """Ошибка вне таблицы §9: так делать нельзя, ответ — 500."""

    code = "orphan"


class OutdatedError(ConflictError):
    """Ошибка модуля с полями для клиента: `current` уходит в ответ, `internal` — нет."""

    code = "outdated"
    public_params = ("current", "documents")


ERRORS: dict[str, Exception] = {
    "not_authenticated": NotAuthenticatedError(),
    "not_found": NotFoundError(),
    "forbidden": ForbiddenError(),
    "restricted": RestrictedError(
        restriction="posting_blocked", until=datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    ),
    "conflict": ConflictError(),
    "outdated": OutdatedError(current="v2", documents=["terms"], internal="x-internal"),
    "concurrent": ConcurrentModificationError(),
    "stale": StaleVersionError(expected=3, actual=4),
    "invalid": DomainValidationError(),
    "limited": RateLimitedError(retry_after=30),
    "external": ExternalServiceError(provider="telegram"),
    "orphan": OrphanError(),
    "bug": ProgrammingError("forgot to save"),
    "crash": RuntimeError("boom"),
}


class BudgetIn(BaseModel):
    min: int
    max: int


class JobIn(BaseModel):
    title: str
    budget: BudgetIn


router = sample_router()


@router.get("/raise/{name}")
async def raise_error(name: str) -> None:
    raise ERRORS[name]


@router.post("/jobs")
async def create_job(job: JobIn) -> dict[str, str]:
    return {"title": job.title}


@router.get("/shared")
async def read_shared() -> dict[str, str]:
    return {}


@router.patch("/shared")
async def change_shared() -> dict[str, str]:
    return {}


@router.get("/locale")
@inject
async def current_locale(locale: FromDishka[Locale]) -> dict[str, str]:
    return {"locale": locale}


@pytest.fixture
async def client(offline_settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async with http_client(offline_settings, router) as client:
        yield client


def _problem(response: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body: dict[str, Any] = response.json()
    assert body["status"] == status
    assert body["code"] == code
    assert body["type"] == f"https://api.example.test/problems/{code.replace('_', '-')}"
    assert body["title"]
    assert len(body["trace_id"]) == 32
    return body


# --- /up и базовый формат -----------------------------------------------------------------


async def test_up_answers_without_database(client: httpx.AsyncClient) -> None:
    response = await client.get("/up")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert (await client.head("/up")).status_code == 200


async def test_unknown_route_is_problem_json(client: httpx.AsyncClient) -> None:
    body = _problem(await client.get("/api/v1/nope"), 404, "not_found")
    assert set(body) == {"type", "title", "status", "code", "detail", "trace_id"}
    assert body["title"] == "Not Found"


async def test_wrong_method_lists_all_methods_of_path(client: httpx.AsyncClient) -> None:
    response = await client.delete("/api/v1/test/jobs")
    _problem(response, 405, "method_not_allowed")
    assert response.headers["allow"] == "POST"
    shared = await client.put("/api/v1/test/shared")
    assert shared.headers["allow"] == "GET, PATCH"


@pytest.mark.parametrize("path", ["/api/v1/test/shared", "/up"])
async def test_allow_only_lists_supported_methods(client: httpx.AsyncClient, path: str) -> None:
    response = await client.put(path)
    assert response.status_code == 405
    for method in response.headers["allow"].split(", "):
        allowed = await client.request(method, path)
        assert allowed.status_code == 200, method


# --- таблица ADR-0020 §9 ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "status", "code"),
    [
        ("not_authenticated", 401, "not_authenticated"),
        ("not_found", 404, "not_found"),
        ("forbidden", 403, "forbidden"),
        ("restricted", 403, "restricted"),
        ("conflict", 409, "conflict"),
        ("concurrent", 409, "concurrent_modification"),
        ("stale", 412, "stale_version"),
        ("invalid", 422, "validation_failed"),
        ("limited", 429, "rate_limited"),
        ("external", 503, "external_service_unavailable"),
        ("orphan", 500, "internal_error"),
        ("bug", 500, "internal_error"),
        ("crash", 500, "internal_error"),
    ],
)
async def test_error_classes_map_to_status(
    client: httpx.AsyncClient, name: str, status: int, code: str
) -> None:
    response = await client.get(f"/api/v1/test/raise/{name}", headers={"traceparent": TRACEPARENT})
    body = _problem(response, status, code)
    assert body["trace_id"] == TRACE_ID


async def test_details_of_failures_are_not_leaked(client: httpx.AsyncClient) -> None:
    for name in ("external", "bug", "crash", "stale"):
        response = await client.get(f"/api/v1/test/raise/{name}")
        text = response.text
        assert "telegram" not in text
        assert "forgot" not in text
        assert "boom" not in text
        assert "expected" not in text


async def test_unexpected_error_is_logged_with_trace(client: httpx.AsyncClient) -> None:
    with capture_logs() as logs:
        await client.get("/api/v1/test/raise/crash", headers={"traceparent": TRACEPARENT})
    [error] = [entry for entry in logs if entry["event"] == "http_unhandled_error"]
    assert error["log_level"] == "error"
    assert error["path"] == "/api/v1/test/raise/crash"


async def test_restricted_carries_restriction_and_until(client: httpx.AsyncClient) -> None:
    body = _problem(await client.get("/api/v1/test/raise/restricted"), 403, "restricted")
    assert body["restriction"] == "posting_blocked"
    assert body["until"] == "2026-10-05T09:00:00Z"


async def test_public_params_become_problem_fields(client: httpx.AsyncClient) -> None:
    body = _problem(await client.get("/api/v1/test/raise/outdated"), 409, "outdated")
    assert (body["current"], body["documents"]) == ("v2", ["terms"])
    assert "internal" not in body
    assert "x-internal" not in str(body)


async def test_rate_limited_sets_retry_after(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/test/raise/limited")
    _problem(response, 429, "rate_limited")
    assert response.headers["retry-after"] == "30"


async def test_not_authenticated_asks_for_bearer(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/test/raise/not_authenticated")
    assert response.headers["www-authenticate"] == "Bearer"


# --- валидация запроса --------------------------------------------------------------------


async def test_body_validation_lists_field_errors(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/test/jobs", json={"title": "Кран", "budget": {"min": 1, "max": "много"}}
    )
    body = _problem(response, 422, "validation_error")
    assert body["errors"] == [
        {"field": "budget.max", "code": "int_parsing", "message": body["errors"][0]["message"]}
    ]


async def test_malformed_json_is_bad_request(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/test/jobs", content=b"{", headers={"content-type": "application/json"}
    )
    _problem(response, 400, "malformed_request")


# --- X-Client и 426 -----------------------------------------------------------------------


@pytest.mark.parametrize("header", ["tma/1.2.0", "tma/1.10", "tma/2", "ios/0.1.0", None])
async def test_supported_or_unknown_clients_pass(
    client: httpx.AsyncClient, header: str | None
) -> None:
    headers = {"x-client": header} if header else {}
    response = await client.get("/api/v1/test/locale", headers=headers)
    assert response.status_code == 200


@pytest.mark.parametrize("header", ["tma/1.1.9", "tma/1", "tma/0.9.0"])
async def test_outdated_client_gets_426(client: httpx.AsyncClient, header: str) -> None:
    body = _problem(
        await client.get("/api/v1/test/locale", headers={"x-client": header}),
        426,
        "client_upgrade_required",
    )
    assert body["platform"] == "tma"
    assert body["min_version"] == "1.2.0"


@pytest.mark.parametrize("header", ["tma", "tma/", "TMA/1.0", "tma/1.0.0.0", "tma/v1", "../1"])
async def test_malformed_client_header_is_bad_request(
    client: httpx.AsyncClient, header: str
) -> None:
    response = await client.get("/api/v1/test/locale", headers={"x-client": header})
    _problem(response, 400, "invalid_client_header")


async def test_client_version_is_not_checked_outside_api(client: httpx.AsyncClient) -> None:
    assert (await client.get("/up", headers={"x-client": "tma/0.1"})).status_code == 200


# --- X-Request-ID, traceparent, Accept-Language, access-лог -------------------------------


async def test_request_id_is_echoed_or_generated(client: httpx.AsyncClient) -> None:
    kept = await client.get("/up", headers={"x-request-id": "tma-abc_123.4"})
    assert kept.headers["x-request-id"] == "tma-abc_123.4"
    replaced = await client.get("/up", headers={"x-request-id": "evil\nheader value"})
    assert replaced.headers["x-request-id"] != "evil\nheader value"
    assert len(replaced.headers["x-request-id"]) == 32
    generated = await client.get("/api/v1/nope")
    assert len(generated.headers["x-request-id"]) == 32


@pytest.mark.parametrize("traceparent", [None, "garbage", f"00-{'0' * 32}-00f067aa0ba902b7-01"])
async def test_trace_id_is_generated_without_valid_traceparent(
    client: httpx.AsyncClient, traceparent: str | None
) -> None:
    headers = {"traceparent": traceparent} if traceparent else {}
    body = (await client.get("/api/v1/nope", headers=headers)).json()
    assert len(body["trace_id"]) == 32
    assert body["trace_id"] != "0" * 32


@pytest.mark.parametrize(
    ("header", "locale"),
    [
        (None, "ru"),
        ("sr-Latn", "sr-Latn"),
        ("sr-Cyrl-RS", "sr-Cyrl"),
        ("sr", "sr-Latn"),
        ("de-DE, sr-Cyrl;q=0.8, ru;q=0.9", "ru"),
        ("en-US,en;q=0.9", "en"),
        ("de, fr", "ru"),
        ("ru;q=0, sr-Latn;q=0.5", "sr-Latn"),
        ("ru;q=abc, sr-Cyrl", "sr-Cyrl"),
    ],
)
async def test_locale_from_accept_language(
    client: httpx.AsyncClient, header: str | None, locale: str
) -> None:
    headers = {"accept-language": header} if header else {}
    response = await client.get("/api/v1/test/locale", headers=headers)
    assert response.json() == {"locale": locale}


async def test_access_log_has_status_and_skips_up(client: httpx.AsyncClient) -> None:
    with capture_logs() as logs:
        await client.get("/api/v1/nope", headers={"x-request-id": "req-1"})
        await client.get("/up")
    requests = [entry for entry in logs if entry["event"] == "http_request"]
    assert len(requests) == 1
    assert requests[0]["status"] == 404
    assert requests[0]["path"] == "/api/v1/nope"
    assert "duration_ms" in requests[0]


# --- OpenAPI ------------------------------------------------------------------------------


async def test_openapi_uses_module_operation_ids(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/api/v1/openapi.json")).json()
    ids = [op["operationId"] for path in spec["paths"].values() for op in path.values()]
    assert "test_create_job" in ids
    assert len(ids) == len(set(ids))
    assert "/up" not in spec["paths"]
