"""Ошибки API на языке запроса (DEVELOPMENT_PLAN 1.2, ADR-0013)."""

from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import BaseModel, Field

from app.platform.kernel.errors import RateLimitedError
from app.platform.settings import Settings
from tests.plugins.http import http_client, sample_router

pytestmark = pytest.mark.unit

router = sample_router()


class NameIn(BaseModel):
    name: str = Field(max_length=5)
    age: int


@router.post("/names")
async def create_name(body: NameIn) -> dict[str, str]:
    return {"name": body.name}


@router.get("/limited")
async def limited() -> None:
    raise RateLimitedError(retry_after=30)


@pytest.fixture
async def client(offline_settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async with http_client(offline_settings, router) as client:
        yield client


@pytest.mark.parametrize(
    ("language", "detail"),
    [
        (None, "Не найдено."),
        ("ru", "Не найдено."),
        ("sr-Cyrl", "Није пронађено."),
        ("sr-Latn", "Nije pronađeno."),
        ("sr", "Nije pronađeno."),
        ("en", "Не найдено."),
    ],
)
async def test_detail_is_in_request_language(
    client: httpx.AsyncClient, language: str | None, detail: str
) -> None:
    headers = {"accept-language": language} if language else {}
    body = (await client.get("/api/v1/nope", headers=headers)).json()
    assert body["detail"] == detail


async def test_detail_uses_error_parameters(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/v1/test/limited", headers={"accept-language": "sr-Latn"})).json()
    assert body["detail"] == "Previše zahteva. Pokušajte ponovo za 30 s."


async def test_field_errors_are_localized(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/test/names", json={"name": "Александра"}, headers={"accept-language": "ru"}
    )
    body = response.json()
    assert body["detail"] == "Проверьте введённые данные."
    messages = {e["field"]: e["message"] for e in body["errors"]}
    assert messages == {"name": "Максимум символов: 5.", "age": "Обязательное поле."}


async def test_middleware_errors_are_localized(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/v1/nope", headers={"x-client": "tma/0.1", "accept-language": "sr-Cyrl"}
    )
    assert response.status_code == 426
    assert response.json()["detail"] == "Ажурирајте Telegram да бисте наставили."
