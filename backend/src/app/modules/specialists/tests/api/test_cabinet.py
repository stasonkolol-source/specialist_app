"""Кабинет исполнителя `/me/profile*` (DEVELOPMENT_PLAN 2.8a): мастер S32a–c через API."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from tests.plugins.http import HttpApp

from app.platform.settings import Settings

from .conftest import Cabinet, cabinet_for

pytestmark = pytest.mark.integration


async def test_wizard_builds_a_profile_and_sends_it_to_review(cabinet: Cabinet) -> None:
    assert (await cabinet.get()).status_code == 404

    created = await cabinet.create()
    assert created.status_code == 201, created.text
    profile = created.json()
    assert (profile["kind"], profile["status"], profile["display_name"]) == ("pro", "draft", "Ana")
    assert profile["missing"] == ["category_ids", "headline", "work_modes", "services"]
    assert profile["completeness"]["percent"] == 0
    assert created.headers["etag"] == '"1"'

    edited = await cabinet.call(
        "PATCH",
        version=1,
        headline="Электрик, 10 лет опыта",
        about="Проводка, розетки, щитки",
        languages=["ru", "sr"],
        work_modes=["at_client"],
        travel_radius_km=5,
    )
    assert edited.status_code == 200, edited.text
    category = await cabinet.category()
    districts = await cabinet.districts()
    assert (await cabinet.call("PUT", "/categories", category_ids=[category])).status_code == 200
    areas = await cabinet.call("PUT", "/areas", district_ids=districts)
    assert areas.json()["district_ids"] == districts
    assert areas.json()["missing"] == ["services"]  # прайс — следующий шаг мастера

    no_prices = await cabinet.call("POST", "/submit")
    assert (no_prices.status_code, no_prices.json()["missing"]) == (409, ["services"])
    await cabinet.add_service()  # первая позиция прайса (S32c)
    # полнота для кабинета S33: «о себе» короче пары предложений, у позиции нет описания
    hints = [(h["code"], h["count"]) for h in (await cabinet.get()).json()["completeness"]["hints"]]
    assert hints == [("about", None), ("service_descriptions", 1)]
    submitted = await cabinet.call("POST", "/submit")

    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "pending_review"
    switched = await cabinet.call("PATCH", kind="casual")
    assert (switched.status_code, switched.json()["code"]) == (409, "profile_state_conflict")
    jobs = await cabinet.scalar(
        "SELECT count(*) FROM procrastinate_jobs WHERE task_name = 'moderation.auto_check'"
        " AND args->'payload'->>'entity_id' = :id",
        id=profile["id"],
    )
    assert jobs == 1  # конвейер модерации получил профиль


async def test_one_profile_per_user_and_stale_edits_are_refused(cabinet: Cabinet) -> None:
    assert (await cabinet.create()).status_code == 201

    again = await cabinet.create(kind="casual")
    stale = await cabinet.call("PATCH", version=7, headline="x")

    assert (again.status_code, again.json()["code"]) == (409, "profile_exists")
    assert stale.status_code == 412


async def test_incomplete_profile_is_not_sent(cabinet: Cabinet) -> None:
    await cabinet.create()

    response = await cabinet.call("POST", "/submit")

    assert response.status_code == 409
    assert response.json()["code"] == "profile_incomplete"
    assert response.json()["missing"] == ["category_ids", "headline", "work_modes", "services"]


async def test_dictionaries_are_checked(cabinet: Cabinet) -> None:
    await cabinet.create()
    engine = await cabinet.app.container.get(AsyncEngine)
    async with engine.connect() as conn:
        foreign = (
            await conn.execute(
                text(
                    "SELECT d.id FROM geo.districts d JOIN geo.cities c ON c.id = d.city_id"
                    " WHERE c.slug <> 'novi-sad' LIMIT 1"
                )
            )
        ).scalar()

    category = await cabinet.call("PUT", "/categories", category_ids=[999_999])
    assert (category.status_code, category.json()["code"]) == (422, "category_not_allowed")
    if foreign is not None:
        area = await cabinet.call("PUT", "/areas", district_ids=[int(foreign)])
        assert (area.status_code, area.json()["code"]) == (422, "district_not_allowed")


async def test_casual_profile_stays_out_of_the_catalog(cabinet: Cabinet) -> None:
    created = await cabinet.create(kind="casual", display_name="Марко")

    assert (created.json()["listed_in_catalog"], created.json()["display_name"]) == (
        False,
        "Марко",
    )
    # S32a: вернулись на первый шаг и выбрали «Специалист» — тип черновика меняется
    switched = await cabinet.call("PATCH", version=1, kind="pro")
    assert (switched.json()["kind"], switched.json()["listed_in_catalog"]) == ("pro", True)


async def test_rules_must_be_accepted_first(web: HttpApp, settings: Settings) -> None:
    newcomer = await cabinet_for(web, settings, rules=False)

    response = await newcomer.create()

    assert (response.status_code, response.json()["code"]) == (403, "consent_required")
