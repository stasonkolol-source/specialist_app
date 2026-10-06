"""Своя заявка клиента (DEVELOPMENT_PLAN 5.6, S22 и S23): в «Моих заявках» — число новых откликов;
отклики на S23 — карточками с исполнителем (профиль, «Новый специалист», подработка без профиля),
«Откликнулся первым» и меткой новых. Ответ отмечает отклики просмотренными: второй раз они уже не
новые, бейдж S22 гаснет, а версия заявки не меняется. Чужая заявка — 404. Данные коммитятся.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.entrypoints._wiring import module_routers
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from tests.integration.test_invites import Invites
from tests.integration.test_responses import API
from tests.plugins.http import HttpApp, http_app
from tests.plugins.round_trips import round_trips

pytestmark = pytest.mark.integration


@pytest.fixture
async def web(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[HttpApp]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(storage_settings, *module_routers(), client_ip=ip) as app:
        yield app


@pytest.fixture
async def world(web: HttpApp, storage_settings: Settings) -> AsyncIterator[Invites]:
    created = Invites(web, storage_settings)
    yield created
    engine = await web.container.get(AsyncEngine)
    async with engine.begin() as conn:
        for user_id in created.users:
            await conn.execute(
                text(
                    "DELETE FROM procrastinate_jobs WHERE status = 'todo' AND args::text LIKE :id"
                ),
                {"id": f"%{user_id}%"},
            )


async def cards(world: Invites, client: UserId, job_id: UUID) -> list[dict[str, Any]]:
    reply = await world.app.client.get(
        f"{API}/jobs/{job_id}/response-cards", headers=world.headers(client)
    )
    assert reply.status_code == 200, reply.text
    items: list[dict[str, Any]] = reply.json()["items"]
    return items


async def fresh(world: Invites, client: UserId, job_id: UUID) -> int | None:
    reply = await world.app.client.get(f"{API}/me/jobs", headers=world.headers(client))
    found = [item for item in reply.json()["items"] if item["id"] == str(job_id)]
    value: int | None = found[0]["new_responses"]
    return value


@pytest.mark.authz
async def test_new_responses_become_seen_on_the_response_cards(world: Invites) -> None:
    client = await world.user("Елена К.")
    job_id = await world.job(client)
    pro, _ = await world.specialist("Ana")
    casual = await world.user("Марко")
    for performer in (pro, casual):
        assert (await world.respond(performer, job_id)).status_code == 201
    # проверка текста пройдена — строкой: конвейер модерации этому тесту не нужен
    await world.execute(
        "UPDATE jobs.responses SET review = 'clear', updated_at = now() WHERE job_id = :job",
        job=job_id,
    )
    version = await world.scalar("SELECT version FROM jobs.jobs WHERE id = :id", id=job_id)

    assert await fresh(world, client, job_id) == 2
    first = await cards(world, client, job_id)
    again = await cards(world, client, job_id)

    assert [card["is_new"] for card in first] == [True, True]
    assert [card["is_new"] for card in again] == [False, False]
    assert await fresh(world, client, job_id) == 0
    by_name = {card["performer"]["display_name"]: card for card in first}
    ana, marko = by_name["Ana"], by_name["Марко"]
    assert ana["is_first"] is True
    assert (ana["performer"]["kind"], ana["performer"]["is_new"]) == ("pro", True)
    assert ana["performer"]["profile_id"] is not None
    assert (marko["performer"]["kind"], marko["performer"]["profile_id"]) == (None, None)
    assert marko["price"] == {"type": "fixed", "amount": {"amount": 350_000, "currency": "RSD"}}
    assert marko["availability_note"] == "Сегодня, 19:00"
    assert await world.scalar("SELECT version FROM jobs.jobs WHERE id = :id", id=job_id) == version
    owner = (await world.get(job_id, client)).json()
    assert owner["new_responses"] == 0
    stranger = await world.app.client.get(
        f"{API}/jobs/{job_id}/response-cards", headers=world.headers(await world.user())
    )
    assert (stranger.status_code, stranger.json()["code"]) == (404, "job_not_found")


async def test_response_cards_are_read_in_batches(world: Invites) -> None:
    """Перф-аудит: карточки S23 читаются пачками — запросов столько же при пяти откликах, что и
    при одном, — а опрос без новых откликов ничего не пишет."""
    client = await world.user()
    job_id = await world.job(client)
    district = await world.scalar("SELECT id FROM geo.districts WHERE slug = 'liman-3'")
    for index in range(5):
        performer, profile_id = await world.specialist(f"Pro {index}")
        await world.execute(
            "INSERT INTO specialists.service_areas (profile_id, district_id, position)"
            " VALUES (:profile, :district, 0)",
            profile=profile_id,
            district=district,
        )
        assert (await world.respond(performer, job_id)).status_code == 201
    await world.execute(
        "UPDATE jobs.responses SET review = 'clear', updated_at = now() WHERE job_id = :job",
        job=job_id,
    )
    first = await cards(world, client, job_id)
    engine = await world.app.container.get(AsyncEngine)
    with round_trips(engine) as trips:
        again = await cards(world, client, job_id)

    assert [card["is_new"] for card in first] == [True] * 5
    assert [card["is_new"] for card in again] == [False] * 5
    assert {card["performer"]["district"]["id"] for card in again} == {district}
    # заявка, отклики, карточки профилей, санкции авторов, рейтинги, имена; районы — из
    # снимка справочника; было 35 запросов и UPDATE на каждый опрос
    assert trips.queries == 6, trips.statements
    assert (trips.begins, trips.ends) == (0, 0)


async def test_whole_city_performer_is_not_put_in_a_district(world: Invites) -> None:
    """QA SMOKE-6: у исполнителя «Весь Нови-Сад» (все кварталы города) район на карточке S23 —
    не первый по алфавиту, а «весь город»; у выбравшего районы — первый из них."""
    client = await world.user()
    job_id = await world.job(client)
    everywhere, everywhere_profile = await world.specialist("Весь город")
    liman, liman_profile = await world.specialist("Лиман")
    await world.execute(
        "INSERT INTO specialists.service_areas (profile_id, district_id, position)"
        " SELECT :profile, d.id, row_number() OVER (ORDER BY d.slug) - 1 FROM geo.districts d"
        " JOIN specialists.profiles p ON p.id = :profile AND d.city_id = p.city_id"
        " WHERE d.kind = 'neighborhood' AND d.is_active",
        profile=everywhere_profile,
    )
    district = await world.scalar("SELECT id FROM geo.districts WHERE slug = 'liman-3'")
    await world.execute(
        "INSERT INTO specialists.service_areas (profile_id, district_id, position)"
        " VALUES (:profile, :district, 0)",
        profile=liman_profile,
        district=district,
    )
    for performer in (everywhere, liman):
        assert (await world.respond(performer, job_id)).status_code == 201
    await world.execute(
        "UPDATE jobs.responses SET review = 'clear', updated_at = now() WHERE job_id = :job",
        job=job_id,
    )

    by_name = {
        card["performer"]["display_name"]: card["performer"]
        for card in await cards(world, client, job_id)
    }

    assert (by_name["Весь город"]["whole_city"], by_name["Весь город"]["district"]) == (True, None)
    assert by_name["Лиман"]["whole_city"] is False
    assert by_name["Лиман"]["district"]["id"] == district


async def test_response_on_review_is_neither_shown_nor_new(world: Invites) -> None:
    client = await world.user()
    job_id = await world.job(client)
    performer = await world.user()
    assert (await world.respond(performer, job_id)).status_code == 201

    assert await fresh(world, client, job_id) == 0
    assert await cards(world, client, job_id) == []
