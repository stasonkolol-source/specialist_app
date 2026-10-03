"""BFF карточки специалиста S08–S11 (DEVELOPMENT_PLAN 4.5, 4.6) сквозь модули: профиль, прайс,
портфолио и рейтинг, ETag, 404 для невидимого профиля. Данные коммитятся.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from app.modules.identity.api import RestrictionKind
from app.modules.specialists.application.use_cases.add_portfolio_work import (
    AddPortfolioWork,
    AddPortfolioWorkCommand,
)
from app.modules.specialists.application.use_cases.hide_profile import (
    HideProfile,
    HideProfileCommand,
)
from app.platform.kernel.ids import MediaId, new_id
from app.platform.settings import Settings
from tests.plugins.http import HttpApp, http_app
from tests.plugins.search import NAME, Specialist

pytestmark = pytest.mark.integration

API = "/api/v1/specialists"


@pytest.fixture
async def web(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[HttpApp]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(storage_settings, client_ip=ip) as app:
        yield app


async def photo(specialist: Specialist, status: str = "ready") -> MediaId:
    """Файл портфолио владельца: готовый — с вариантами, иначе — ещё обрабатывается."""
    media_id = new_id()
    variants = (
        {"thumb": {"key": f"m/{media_id}/thumb.webp", "w": 320, "h": 240}}
        if status == "ready"
        else {}
    )
    await specialist.execute(
        "INSERT INTO media.assets (id, owner_id, kind, purpose, status, bucket, object_key,"
        " mime_type, size_bytes, variants) VALUES (:id, :owner, 'image', 'portfolio', :status,"
        " 'media', :key, 'image/jpeg', 1000, CAST(:variants AS jsonb))",
        id=media_id,
        owner=specialist.user_id,
        status=status,
        key=f"portfolio/2026/10/{media_id}/original",
        variants=json.dumps(variants),
    )
    return MediaId(media_id)


async def published(app: HttpApp) -> Specialist:
    specialist = Specialist(app.container)
    await specialist.publish()
    for caption, status in (("Люстра в гостиной", "ready"), (None, "processing")):
        media_id = await photo(specialist, status)
        await specialist.call(
            AddPortfolioWork,
            AddPortfolioWorkCommand(
                actor_id=specialist.user_id, media_id=media_id, caption=caption
            ),
        )
    return specialist


async def get(app: HttpApp, path: str, **headers: str) -> httpx.Response:
    return await app.client.get(f"{API}/{path}", headers=headers)


async def test_card_comes_in_one_request_with_etag(web: HttpApp) -> None:
    specialist = await published(web)

    response = await get(web, str(specialist.profile_id), **{"accept-language": "ru"})

    assert response.status_code == 200
    card: dict[str, Any] = response.json()
    assert (card["display_name"], card["kind"], card["is_new"]) == (NAME, "pro", True)
    assert card["headline"] == "Электрик, 10 лет"
    assert [category["name"] for category in card["categories"]] == ["Электрик"]
    assert card["city"]["name"] == "Нови-Сад"
    assert card["district"] == card["areas"][0]
    assert (card["services_count"], card["services"][0]["title"]) == (1, "Montaža lustera")
    # обрабатываемый файл клиенту не виден
    assert (card["works_count"], card["works"][0]["caption"]) == (1, "Люстра в гостиной")
    assert card["works"][0]["photo"]["variants"][0]["name"] == "thumb"
    assert response.headers["vary"] == "Accept-Language"

    again = await get(
        web, str(specialist.profile_id), **{"if-none-match": response.headers["etag"]}
    )
    assert again.status_code == 304


async def test_names_follow_the_language(web: HttpApp) -> None:
    specialist = await published(web)

    card = (await get(web, str(specialist.profile_id), **{"accept-language": "sr-Latn"})).json()

    assert card["city"]["name"] == "Novi Sad"
    assert [category["name"] for category in card["categories"]] == ["Električar"]


async def test_price_list_and_portfolio_pages(web: HttpApp) -> None:
    specialist = await published(web)

    services = (await get(web, f"{specialist.profile_id}/services")).json()
    works = (await get(web, f"{specialist.profile_id}/portfolio")).json()

    assert [item["price_min"] for item in services["items"]] == [
        {"amount": 150_000, "currency": "RSD"}
    ]
    assert [group["id"] for group in services["categories"]] == [specialist.category]
    assert [item["caption"] for item in works["items"]] == ["Люстра в гостиной"]


async def test_reviews_page_and_card_show_the_rating(web: HttpApp) -> None:
    specialist = await published(web)

    empty = (await get(web, f"{specialist.profile_id}/reviews")).json()
    assert empty == {
        "summary": {
            "rating": None,
            "count": 0,
            "is_new": True,
            "distribution": [0, 0, 0, 0, 0],
            "criteria": {},
        },
        "items": [],
        "next_cursor": None,
    }
    # агрегат пересчитывают отзывы по сделкам (7.2) — здесь строкой; показ — байесовское среднее
    await specialist.execute(
        "INSERT INTO reviews.rating_aggregates (subject_profile_id, rating_count, rating_avg,"
        " rating_bayes, rating_lower_bound, distribution, criteria_avg) VALUES (:id, 37, 4.92,"
        " 4.87, 4.5, '{0,0,1,1,35}', CAST(:criteria AS jsonb))",
        id=specialist.profile_id,
        criteria=json.dumps({"quality": 4.9, "price": 4.8}),
    )

    summary = (await get(web, f"{specialist.profile_id}/reviews")).json()["summary"]
    card = (await get(web, str(specialist.profile_id))).json()

    assert summary == {
        "rating": 4.9,
        "count": 37,
        "is_new": False,
        "distribution": [0, 0, 1, 1, 35],
        "criteria": {"quality": 4.9, "price": 4.8},
    }
    assert (card["rating"], card["rating_count"], card["is_new"]) == (4.9, 37, False)


async def test_hidden_profile_is_not_found(web: HttpApp) -> None:
    specialist = await published(web)

    await specialist.call(HideProfile, HideProfileCommand(actor_id=specialist.user_id))

    for path in ("", "/services", "/portfolio", "/reviews"):
        response = await get(web, f"{specialist.profile_id}{path}")
        assert (response.status_code, response.json()["code"]) == (404, "not_found"), path


async def test_suspended_author_is_not_found(web: HttpApp) -> None:
    specialist = await published(web)

    await specialist.restrict(RestrictionKind.SUSPENDED, None)

    assert (await get(web, str(specialist.profile_id))).status_code == 404


async def test_unknown_profile_is_not_found(web: HttpApp) -> None:
    assert (await get(web, str(new_id()))).status_code == 404
    assert (await get(web, "not-a-uuid")).status_code == 422
