"""BFF сделки S26 (DEVELOPMENT_PLAN 6.2): сторонам — условия, вторая сторона, место и вехи;
адрес — клиенту и выбранному исполнителю; чужая сделка — 404. Данные коммитятся."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import module_routers
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from tests.plugins.http import HttpApp, bearer, http_app
from tests.plugins.identity import accept_rules, insert_user
from tests.plugins.round_trips import round_trips

pytestmark = pytest.mark.integration

API = "/api/v1"
ADDRESS = "бул. Цара Лазара, 56, кв. 12"


@pytest.fixture
async def web(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[HttpApp]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(storage_settings, *module_routers(), client_ip=ip) as app:
        yield app


async def execute(app: HttpApp, sql: str, **params: object) -> None:
    engine = await app.container.get(AsyncEngine)
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


async def user(app: HttpApp, name: str) -> UserId:
    async with app.container() as request:
        session = await request.get(AsyncSession)
        user_id = await insert_user(session)
        await accept_rules(session, user_id)
    await execute(
        app, "UPDATE identity.users SET display_name = :n WHERE id = :id", n=name, id=user_id
    )
    return user_id


async def call(app: HttpApp, settings: Settings, who: UserId, method: str, path: str) -> Any:
    return await app.client.request(method, f"{API}{path}", headers=bearer(settings, who))


async def test_deal_card_for_both_sides(web: HttpApp, storage_settings: Settings) -> None:
    client, performer, stranger = (
        await user(web, "Елена К."),
        await user(web, "Марко П."),
        await user(web, "Чужой"),
    )
    job_id = new_id()
    now = datetime.now(UTC)
    await execute(
        web,
        "INSERT INTO jobs.jobs (id, client_id, status, title, description, content_lang,"
        " category_id, category_path, urgency, budget_type, budget_min, city_id, district_id,"
        " address_private, point_exact, preferred_from, preferred_to, published_at, expires_at,"
        " version) SELECT :id, :client, 'published', 'Повесить люстру', '', 'ru', c.id,"
        " ARRAY[c.id], 'today', 'fixed', 500000, ci.id, d.id, :address,"
        " ST_GeogFromText('SRID=4326;POINT(19.84 45.25)'), :start, :end, :published,"
        " :expires, 1 FROM geo.cities ci JOIN geo.districts d ON d.slug = 'liman-3',"
        " (SELECT min(id) AS id FROM catalog.categories WHERE parent_id IS NOT NULL"
        " AND is_active AND jobs_enabled AND risk_level = 0) c WHERE ci.slug = 'novi-sad'",
        id=job_id,
        client=client,
        address=ADDRESS,
        start=now + timedelta(hours=6),
        end=now + timedelta(hours=9),
        published=now - timedelta(minutes=30),
        expires=now + timedelta(days=1),
    )
    body = {
        "message": f"Могу сегодня в 19:00. {new_id().hex[-6:]}",
        "price_type": "fixed",
        "price_amount": 350_000,
        "availability_note": "Сегодня, 19:00",
    }
    headers = bearer(storage_settings, performer) | {"Idempotency-Key": new_id().hex}
    reply = await web.client.post(f"{API}/jobs/{job_id}/responses", json=body, headers=headers)
    assert reply.status_code == 201, reply.text
    response_id = reply.json()["id"]
    await execute(
        web, "UPDATE jobs.responses SET review = 'clear' WHERE id = :id", id=UUID(response_id)
    )
    accepted = await call(web, storage_settings, client, "POST", f"/responses/{response_id}/accept")
    deal_id = accepted.json()["deal_id"]
    await call(web, storage_settings, performer, "POST", f"/deals/{deal_id}/complete")

    for_client = (await call(web, storage_settings, client, "GET", f"/deals/{deal_id}/card")).json()
    for_performer = (
        await call(web, storage_settings, performer, "GET", f"/deals/{deal_id}/card")
    ).json()
    foreign = await call(web, storage_settings, stranger, "GET", f"/deals/{deal_id}/card")

    assert (for_client["my_role"], for_client["status"], for_client["title"]) == (
        "client",
        "agreed",
        "Повесить люстру",
    )
    assert for_client["counterpart"]["role"] == "performer"
    assert for_client["counterpart"]["display_name"] == "Марко П."  # без профиля — подработка
    assert for_client["price"] == {
        "type": "fixed",
        "amount": {"amount": 350_000, "currency": "RSD"},
    }
    assert for_client["availability_note"] == "Сегодня, 19:00"
    assert for_client["scheduled_at"] is not None  # окно заявки — время сделки
    assert for_client["budget"] == {"amount": 500_000, "currency": "RSD"}
    assert for_client["place"]["district"] is not None
    assert for_client["place"]["address"] == ADDRESS
    timeline = for_client["timeline"]
    assert timeline["responded_at"] is not None
    assert timeline["agreed_at"] is not None
    assert (timeline["my_mark_at"], timeline["other_mark_at"] is not None) == (None, True)
    assert for_performer["my_role"] == "performer"
    assert (
        for_performer["counterpart"] | {"display_name": "Елена К."} == for_performer["counterpart"]
    )
    assert for_performer["counterpart"]["role"] == "client"
    assert for_performer["place"]["address"] == ADDRESS  # выбранному — точный адрес
    assert for_performer["timeline"]["my_mark_at"] is not None
    assert foreign.status_code == 404
    engine = await web.container.get(AsyncEngine)
    with round_trips(engine) as trips:
        again = await call(web, storage_settings, client, "GET", f"/deals/{deal_id}/card")
    assert again.json() == for_client
    # сделка, заявка с откликом, имя второй стороны, её Telegram, отзыв; место — из снимка
    # справочника (было ещё по запросу на город и район)
    assert trips.queries == 6, trips.statements
