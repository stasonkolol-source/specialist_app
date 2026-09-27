"""Курсор и If-Match в HTTP (DEVELOPMENT_PLAN 0.13b, ARCHITECTURE §8.1, §8.4)."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi import Response
from pydantic import BaseModel

from app.platform.db.query import decode_cursor, encode_cursor
from app.platform.http.concurrency import IfMatch, set_etag
from app.platform.http.pagination import PageOut, PageParams
from app.platform.kernel.aggregate import VersionedAggregate
from app.platform.kernel.pagination import Page, PageRequest
from app.platform.settings import Settings
from tests.plugins.http import http_client, sample_router

pytestmark = pytest.mark.unit

ITEMS = list(range(1, 46))


@dataclass
class Item:
    id: int


class ItemOut(BaseModel):
    id: int


def list_items(request: PageRequest) -> Page[Item]:
    """Query-сервис в миниатюре: keyset по id, курсор — последний id страницы."""
    after = decode_cursor(request.cursor, [int])[0] if request.cursor else 0
    rows = [Item(id=i) for i in ITEMS if i > after][: request.limit + 1]
    more = len(rows) > request.limit
    rows = rows[: request.limit]
    return Page(items=tuple(rows), next_cursor=encode_cursor(rows[-1].id) if more else None)


@dataclass(kw_only=True)
class Widget(VersionedAggregate):
    title: str = "Люстра"


router = sample_router()


@router.get("/items")
async def get_items(page: PageParams) -> PageOut[ItemOut]:
    return PageOut[ItemOut].of(list_items(page), lambda item: ItemOut(id=item.id))


@router.patch("/widgets/{widget_id}")
async def rename_widget(widget_id: int, expected: IfMatch, response: Response) -> dict[str, int]:
    widget = Widget(version=3)
    widget.ensure_version(expected)
    widget.version += 1
    set_etag(response, widget.version)
    return {"version": widget.version}


@pytest.fixture
async def client(offline_settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    async with http_client(offline_settings, router) as client:
        yield client


async def test_cursor_walks_all_pages_without_gaps(client: httpx.AsyncClient) -> None:
    seen: list[int] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": 20} | ({"cursor": cursor} if cursor else {})
        body = (await client.get("/api/v1/test/items", params=params)).json()
        seen += [item["id"] for item in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == ITEMS
    assert pages == 3


async def test_default_limit_is_twenty(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/v1/test/items")).json()
    assert len(body["items"]) == 20
    assert set(body) == {"items", "next_cursor"}


@pytest.mark.parametrize("limit", [0, 101, "x"])
async def test_limit_out_of_range_is_validation_error(
    client: httpx.AsyncClient, limit: object
) -> None:
    response = await client.get("/api/v1/test/items", params={"limit": limit})
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "query.limit"


@pytest.mark.parametrize("cursor", ["!!!", "bm90LWpzb24", "WyJhIl0", "x" * 600])
async def test_broken_cursor_is_rejected(client: httpx.AsyncClient, cursor: str) -> None:
    response = await client.get("/api/v1/test/items", params={"cursor": cursor})
    assert response.status_code == 422
    assert response.json()["code"] in {"invalid_cursor", "validation_error"}


@pytest.mark.parametrize(
    ("header", "status"),
    [('"3"', 200), (None, 200), ("*", 200), ('"2"', 412), ('"4"', 412)],
)
async def test_if_match_compares_version(
    client: httpx.AsyncClient, header: str | None, status: int
) -> None:
    headers = {"if-match": header} if header else {}
    response = await client.patch("/api/v1/test/widgets/1", headers=headers)
    assert response.status_code == status
    if status == 200:
        assert response.headers["etag"] == '"4"'
    else:
        assert response.json()["code"] == "stale_version"


@pytest.mark.parametrize("header", ["3", 'W/"3"', '"abc"', '"3", "4"', '""'])
async def test_malformed_if_match_is_rejected(client: httpx.AsyncClient, header: str) -> None:
    response = await client.patch("/api/v1/test/widgets/1", headers={"if-match": header})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_if_match"


async def test_page_schema_in_openapi(client: httpx.AsyncClient) -> None:
    spec = (await client.get("/api/v1/openapi.json")).json()
    params = {p["name"] for p in spec["paths"]["/api/v1/test/items"]["get"]["parameters"]}
    assert params == {"limit", "cursor"}
    patch = spec["paths"]["/api/v1/test/widgets/{widget_id}"]["patch"]
    assert "If-Match" in {p["name"] for p in patch["parameters"]}
