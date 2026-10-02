"""Лента заявок (DEVELOPMENT_PLAN 5.3; ARCHITECTURE §9.6) через API: опубликованные заявки
города, свежие сверху; фильтры — категория с подкатегориями, район, радиус, срочность, бюджет
«от», язык, «только с фото»; курсор; свои и скрытые («не интересно») зритель не видит; счётчик
для «Показать N» и «новых рядом»; карточка с фото и блоком клиента; сохранённые заявки (сердечко
S15, S12) — открытые, новые первыми, до ста. Данные коммитятся: заявки других тестов тоже в
ленте — тест отбирает свои бюджетом, которого у других нет.
"""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import module_routers
from app.entrypoints.seeds import load_city_seeds
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from tests.plugins.http import HttpApp, bearer, http_app
from tests.plugins.identity import accept_rules, insert_user

pytestmark = pytest.mark.integration

API = "/api/v1"
MINE = 900_000_000
"""Бюджет «от», пара: у заявок других тестов такого нет — лента этого теста только из своих."""


@pytest.fixture
async def web(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[HttpApp]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(storage_settings, *module_routers(), client_ip=ip) as app:
        yield app


class World:
    def __init__(self, app: HttpApp, settings: Settings) -> None:
        self.app, self.settings = app, settings
        self.centers = {d.slug: d.center for s in load_city_seeds() for d in s.districts}

    async def scalar(self, sql: str, **params: object) -> Any:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar()

    async def execute(self, sql: str, **params: object) -> None:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)

    async def user(self, name: str = "Ana") -> UserId:
        async with self.app.container() as request:
            session = await request.get(AsyncSession)
            user_id = await insert_user(session)
            await accept_rules(session, user_id)
        await self.execute(
            "UPDATE identity.users SET display_name = :name WHERE id = :id", name=name, id=user_id
        )
        return user_id

    async def category(self, slug: str) -> tuple[int, list[int]]:
        row_id = await self.scalar("SELECT id FROM catalog.categories WHERE slug = :s", s=slug)
        path = await self.scalar("SELECT path FROM catalog.categories WHERE id = :id", id=row_id)
        return int(row_id), list(path)

    async def district(self, slug: str) -> int:
        return int(await self.scalar("SELECT id FROM geo.districts WHERE slug = :s", s=slug))

    async def city(self, slug: str) -> int:
        return int(await self.scalar("SELECT id FROM geo.cities WHERE slug = :s", s=slug))

    async def job(
        self,
        client_id: UserId,
        *,
        category: str = "electrical",
        district: str = "liman-3",
        city: str = "novi-sad",
        status: str = "published",
        urgency: str = "this_week",
        budget: int | None = MINE + 1_000_000,
        languages: tuple[str, ...] = (),
        age: timedelta = timedelta(hours=1),
        expires_in: timedelta = timedelta(days=7),
    ) -> UUID:
        """Заявка строкой: модерация ленте не нужна. Точка — центр района."""
        job_id = new_id()
        category_id, path = await self.category(category)
        center = self.centers[district]
        now = datetime.now(UTC)
        await self.execute(
            "INSERT INTO jobs.jobs (id, client_id, status, title, description, content_lang,"
            " category_id, category_path, urgency, budget_type, budget_min, city_id,"
            " district_id, point_public, languages, published_at, expires_at, version)"
            " VALUES (:id, :client, :status, :title, :description, 'ru', :category, :path,"
            " :urgency, :budget_type, :budget, :city, :district,"
            " ST_GeogFromText(:point), :languages, :published, :expires, 1)",
            id=job_id,
            client=client_id,
            status=status,
            title=f"Заявка {category} {district}",
            description="Слово " * 80,
            category=category_id,
            path=path,
            urgency=urgency,
            budget_type="fixed" if budget is not None else "negotiable",
            budget=budget,
            city=await self.city(city),
            district=await self.district(district) if city == "novi-sad" else None,
            point=f"SRID=4326;POINT({center.lon} {center.lat})",
            languages=list(languages),
            published=now - age if status == "published" else None,
            expires=now + expires_in,
        )
        return job_id

    async def photo(self, owner: UserId, job_id: UUID) -> None:
        media_id = new_id()
        variants = {
            "thumb": {"key": f"m/{media_id}/thumb.webp", "w": 320, "h": 240},
            "md": {"key": f"m/{media_id}/md.webp", "w": 800, "h": 600},
        }
        await self.execute(
            "INSERT INTO media.assets (id, owner_id, kind, purpose, status, bucket, object_key,"
            " mime_type, size_bytes, variants) VALUES (:id, :owner, 'image', 'job', 'ready',"
            " 'media', :key, 'image/jpeg', 1000, CAST(:variants AS jsonb))",
            id=media_id,
            owner=owner,
            key=f"job/2026/10/{media_id}/original",
            variants=json.dumps(variants),
        )
        await self.execute(
            "INSERT INTO jobs.job_media (job_id, media_id, position) VALUES (:job, :media, 0)",
            job=job_id,
            media=media_id,
        )

    def headers(self, user_id: UserId) -> dict[str, str]:
        return bearer(self.settings, user_id)

    async def feed(self, viewer: UserId | None = None, **params: Any) -> dict[str, Any]:
        city = await self.city("novi-sad")
        response = await self.app.client.get(
            f"{API}/jobs",
            params={"city_id": city, "budget_from": MINE, **params},
            headers=self.headers(viewer) if viewer else None,
        )
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    async def ids(self, viewer: UserId | None = None, **params: Any) -> list[str]:
        return [item["id"] for item in (await self.feed(viewer, **params))["items"]]


@pytest.fixture
def world(web: HttpApp, storage_settings: Settings) -> World:
    return World(web, storage_settings)


async def test_feed_is_newest_first_and_filtered(world: World) -> None:
    client = await world.user()
    liman = await world.job(client, age=timedelta(hours=3), languages=("ru",))
    grbavica = await world.job(
        client,
        category="plumbing",
        district="grbavica",
        urgency="asap",
        languages=("sr",),
        age=timedelta(hours=2),
    )
    negotiable = await world.job(client, budget=None, age=timedelta(minutes=30))
    pending = await world.job(client, status="pending_moderation")
    expired = await world.job(client, expires_in=timedelta(minutes=-5))
    elsewhere = await world.job(client, city="beograd", district="liman-3")
    mine = {str(job) for job in (liman, grbavica, negotiable, pending, expired, elsewhere)}

    found = [job for job in await world.ids() if job in mine]

    assert found == [str(grbavica), str(liman)]  # новые сверху; договорная — не «от суммы»
    handyman, _ = await world.category("handyman")
    assert [j for j in await world.ids(category=handyman) if j in mine] == found
    liman_id = await world.district("liman-3")
    assert [j for j in await world.ids(district=liman_id) if j in mine] == [str(liman)]
    assert [j for j in await world.ids(urgency="asap") if j in mine] == [str(grbavica)]
    assert [j for j in await world.ids(lang="sr") if j in mine] == [str(grbavica)]
    center = world.centers["liman-3"]
    near = await world.feed(lat=center.lat, lon=center.lon, radius_km=0.5)
    cards = [item for item in near["items"] if item["id"] in mine]
    assert [card["id"] for card in cards] == [str(liman)]
    assert cards[0]["distance_m"] == 100  # точка в центре района — ближе шага
    assert cards[0]["description"].endswith("…")
    assert cards[0]["budget_min"] == {"amount": MINE + 1_000_000, "currency": "RSD"}


async def test_feed_pages_with_a_cursor(world: World) -> None:
    client = await world.user()
    jobs = [
        await world.job(client, budget=MINE + 5_000_000 + index, age=timedelta(minutes=10 * index))
        for index in range(3)
    ]
    wanted = {str(job) for job in jobs}

    seen: list[str] = []
    cursor = None
    while True:
        page = await world.feed(
            budget_from=MINE + 5_000_000, limit=1, **({"cursor": cursor} if cursor else {})
        )
        seen += [item["id"] for item in page["items"] if item["id"] in wanted]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert seen == [str(job) for job in jobs]
    bad = await world.app.client.get(
        f"{API}/jobs", params={"city_id": await world.city("novi-sad"), "cursor": "oops"}
    )
    assert (bad.status_code, bad.json()["code"]) == (422, "invalid_cursor")


async def test_own_and_hidden_jobs_are_not_in_the_feed(world: World) -> None:
    client, worker = await world.user(), await world.user()
    hidden = await world.job(client, age=timedelta(minutes=5))
    kept = await world.job(client, age=timedelta(minutes=6))
    mine = {str(hidden), str(kept)}

    hide = await world.app.client.post(f"{API}/jobs/{hidden}/hide", headers=world.headers(worker))
    again = await world.app.client.post(f"{API}/jobs/{hidden}/hide", headers=world.headers(worker))

    assert (hide.status_code, again.status_code) == (204, 204)
    assert [j for j in await world.ids(worker) if j in mine] == [str(kept)]
    assert [j for j in await world.ids() if j in mine] == [str(hidden), str(kept)]  # гость
    assert [j for j in await world.ids(client) if j in mine] == []  # свои — не в ленте
    unknown = await world.app.client.post(
        f"{API}/jobs/{new_id()}/hide", headers=world.headers(worker)
    )
    assert (unknown.status_code, unknown.json()["code"]) == (404, "job_not_found")
    guest = await world.app.client.post(f"{API}/jobs/{kept}/hide")
    assert guest.status_code == 401


async def test_count_for_show_n_and_new_nearby(world: World) -> None:
    client = await world.user()
    budget = MINE + 9_000_000
    await world.job(client, budget=budget, age=timedelta(minutes=20))
    await world.job(client, budget=budget, age=timedelta(hours=5))
    city = await world.city("novi-sad")

    total = await world.app.client.get(
        f"{API}/jobs/count", params={"city_id": city, "budget_from": budget}
    )
    fresh = await world.app.client.get(
        f"{API}/jobs/count", params={"city_id": city, "budget_from": budget, "new_hours": 1}
    )

    assert total.json() == {"count": 2}
    assert fresh.json() == {"count": 1}
    half = await world.app.client.get(f"{API}/jobs", params={"city_id": city, "lat": 45.25})
    assert (half.status_code, half.json()["code"]) == (422, "validation_failed")
    radius = await world.app.client.get(f"{API}/jobs", params={"city_id": city, "radius_km": 3})
    assert radius.status_code == 422


async def test_job_card_has_photos_and_the_client_block(world: World) -> None:
    client = await world.user("Елена К.")
    job = await world.job(client)
    await world.photo(client, job)
    await world.job(client, status="closed")  # не публиковалась — не в счёт

    card = await world.app.client.get(f"{API}/jobs/{job}")
    listed = await world.feed()

    assert card.status_code == 200, card.text
    body = card.json()
    assert body["client"]["display_name"] == "Елена К."
    assert body["client"]["jobs_count"] == 1
    assert body["client"]["phone_verified"] is False
    [photo] = body["photos"]
    assert photo["url"].endswith("/md.webp")
    [item] = [item for item in listed["items"] if item["id"] == str(job)]
    assert (item["photos_count"], item["photos"][0]["url"].endswith("/thumb.webp")) == (1, True)
    with_photos = await world.ids(has_photos="true")
    assert str(job) in with_photos


async def test_saved_jobs_are_open_ones_newest_first(world: World) -> None:
    client, worker = await world.user(), await world.user()
    first = await world.job(client)
    second = await world.job(client, category="plumbing")
    closed = await world.job(client)
    pending = await world.job(client, status="pending_moderation")
    headers = world.headers(worker)

    replies = [
        await world.app.client.put(f"{API}/me/favorites/job/{job}", headers=headers)
        for job in (first, second, closed, first)
    ]
    await world.execute("UPDATE jobs.jobs SET status = 'closed' WHERE id = :id", id=closed)
    listed = await world.app.client.get(f"{API}/me/favorites/jobs", headers=headers)

    assert [reply.status_code for reply in replies] == [204, 204, 204, 204]
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert [item["id"] for item in items] == [str(second), str(first)]  # закрытой нет
    assert items[0]["distance_m"] is None
    assert items[0]["description"].endswith("…")
    hidden = await world.app.client.put(f"{API}/me/favorites/job/{pending}", headers=headers)
    assert (hidden.status_code, hidden.json()["code"]) == (404, "job_not_found")
    removed = await world.app.client.delete(f"{API}/me/favorites/job/{second}", headers=headers)
    again = await world.app.client.delete(f"{API}/me/favorites/job/{second}", headers=headers)
    assert (removed.status_code, again.status_code) == (204, 204)
    left = await world.app.client.get(f"{API}/me/favorites/jobs", headers=headers)
    assert [item["id"] for item in left.json()["items"]] == [str(first)]
    guest = await world.app.client.get(f"{API}/me/favorites/jobs")
    assert guest.status_code == 401


async def test_saved_jobs_stop_at_the_limit(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.modules.jobs.application.use_cases.save_job.MAX_SAVED_JOBS", 2)
    client, worker = await world.user(), await world.user()
    jobs = [await world.job(client) for _ in range(3)]
    headers = world.headers(worker)

    saved = [
        await world.app.client.put(f"{API}/me/favorites/job/{job}", headers=headers)
        for job in jobs[:2]
    ]
    full = await world.app.client.put(f"{API}/me/favorites/job/{jobs[2]}", headers=headers)
    repeat = await world.app.client.put(f"{API}/me/favorites/job/{jobs[0]}", headers=headers)

    assert [reply.status_code for reply in saved] == [204, 204]
    assert (full.status_code, full.json()["code"], full.json()["limit"]) == (
        409,
        "saved_jobs_full",
        2,
    )
    assert repeat.status_code == 204  # уже сохранённая — не ошибка и при полном списке
