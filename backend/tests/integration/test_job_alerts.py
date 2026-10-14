"""Подписки на заявки (DEVELOPMENT_PLAN 5.7) через API и задачи: `/me/job-alerts` — создать,
поправить, выключить, удалить, предел и «N заявок за неделю»; `jobs.match_alerts` (SQL §9.6) —
кому уходит карточка B1: категория с подкатегориями, районы, радиус, бюджет, срочность, язык;
своя заявка, выключенная и на паузе подписка — нет; заблокированный в любую сторону и под
санкцией на отклик не получает B1; по карточке на человека, повтор задачи ничего не удваивает,
сверх лимита частоты — в подборку; `notifications.notify_job_matched` — параметры карточки на
языке получателя; подборки `jobs.alert_digests` в час дайджеста; лента `feed=alerts`; удаление
аккаунта стирает подписки. Напоминание о давно не обновлённом профиле
`specialists.stale_profile_reminders` — не чаще раза в 2 недели. Данные коммитятся.
"""

from collections.abc import AsyncIterator, Collection
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import module_routers
from app.modules.jobs.application.alerts import INSTANT_PER_HOUR
from app.modules.jobs.application.ports import AlertMatches
from app.modules.jobs.application.use_cases.catch_up_alert import (
    CatchUpAlert,
    CatchUpAlertCommand,
)
from app.modules.jobs.application.use_cases.create_profile_alert import (
    CreateProfileAlert,
    CreateProfileAlertCommand,
)
from app.modules.jobs.application.use_cases.extend_job import ExtendJob, ExtendJobCommand
from app.modules.jobs.application.use_cases.forget_alerts import (
    ForgetAlerts,
    ForgetAlertsCommand,
)
from app.modules.jobs.application.use_cases.match_alerts import MatchAlerts, MatchAlertsCommand
from app.modules.jobs.application.use_cases.send_alert_digests import (
    SendAlertDigests,
    SendAlertDigestsCommand,
)
from app.modules.jobs.domain.alert import AlertId
from app.modules.jobs.domain.job import JobId
from app.modules.specialists.application.use_cases.remind_stale_profiles import (
    RemindStaleProfiles,
    RemindStaleProfilesCommand,
)
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId, new_id
from app.platform.queue.port import JobQueue
from app.platform.settings import Settings
from app.platform.testing.clock import FakeClock
from tests.integration.test_responses import API, World
from tests.plugins.http import HttpApp, http_app
from tests.plugins.identity import insert_restriction
from tests.plugins.queue import run_queued
from tests.plugins.search import Specialist

pytestmark = pytest.mark.integration

MATCHED = "notifications.notify_job_matched"
DIGEST = "notifications.notify_job_digest"


@pytest.fixture
async def web(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[HttpApp]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(storage_settings, *module_routers(), client_ip=ip) as app:
        yield app


class Alerts(World):
    async def ids(self) -> dict[str, Any]:
        """Город, район Лиман, раздел «Мастер на час» и его подкатегория заявки (World.job)."""
        leaf = await self.scalar(
            "SELECT min(id) FROM catalog.categories WHERE is_active AND jobs_enabled"
            " AND risk_level = 0 AND parent_id IS NOT NULL"
        )
        section = await self.scalar(
            "SELECT parent_id FROM catalog.categories WHERE id = :id", id=leaf
        )
        other = await self.scalar(
            "SELECT min(id) FROM catalog.categories WHERE parent_id IS NULL AND id <> :id"
            " AND is_active AND risk_level = 0",
            id=section,
        )
        return {
            "city": await self.scalar("SELECT id FROM geo.cities WHERE slug = 'novi-sad'"),
            "liman": await self.scalar("SELECT id FROM geo.districts WHERE slug = 'liman-3'"),
            "far": await self.scalar(
                "SELECT min(d.id) FROM geo.districts d JOIN geo.cities c ON c.id = d.city_id"
                " WHERE c.slug = 'novi-sad' AND d.slug <> 'liman-3'"
            ),
            "section": section,
            "leaf": leaf,
            "other": other,
        }

    async def create(
        self, user: UserId, *, delivery: str = "instant", **criteria: Any
    ) -> httpx.Response:
        headers = self.headers(user) | {"Idempotency-Key": new_id().hex}
        return await self.app.client.post(
            f"{API}/me/job-alerts",
            json={"criteria": criteria, "delivery": delivery},
            headers=headers,
        )

    async def created(self, user: UserId, **criteria: Any) -> dict[str, Any]:
        reply = await self.create(user, **criteria)
        assert reply.status_code == 201, reply.text
        body: dict[str, Any] = reply.json()
        return body

    async def match(self, job_id: UUID) -> int:
        async with self.app.container() as request:
            match = await request.get(MatchAlerts)
            return await match(MatchAlertsCommand(job_id=JobId(job_id)))

    async def matched(self, job_id: UUID) -> dict[str, dict[str, Any]]:
        """Поставленные карточки B1 заявки: получатель → payload."""
        rows = await self.rows(
            "SELECT args->'payload' AS payload FROM procrastinate_jobs WHERE task_name = :task"
            " AND args->'payload'->>'job_id' = :job",
            task=MATCHED,
            job=str(job_id),
        )
        return {row["payload"]["user_id"]: row["payload"] for row in rows}

    async def rows(self, sql: str, **params: object) -> list[dict[str, Any]]:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return [dict(row._mapping) for row in await conn.execute(text(sql), params)]


@pytest.fixture
async def world(web: HttpApp, storage_settings: Settings) -> AsyncIterator[Alerts]:
    created = Alerts(web, storage_settings)
    yield created
    for user_id in created.users:  # чужие тесты не должны получить наши задачи и подписки
        await created.execute(
            "DELETE FROM procrastinate_jobs WHERE status = 'todo' AND args::text LIKE :id",
            id=f"%{user_id}%",
        )
    await created.execute("DELETE FROM jobs.alerts WHERE user_id = ANY(:ids)", ids=created.users)


@pytest.mark.authz
async def test_alert_crud_limit_and_week_count(world: Alerts) -> None:
    ids = await world.ids()
    ana = await world.user("Ana")
    client = await world.user("Елена")
    await world.job(client)  # опубликована 30 минут назад: попадёт в «за неделю»

    body = await world.created(
        ana, category_ids=[ids["section"]], city_id=ids["city"], min_budget=200_000
    )

    assert body["delivery"] == "instant"
    assert body["is_active"] is True
    assert body["week_count"] >= 1
    assert body["criteria"]["category_ids"] == [ids["section"]]
    assert body["criteria"]["center"] is None
    listed = await world.app.client.get(f"{API}/me/job-alerts", headers=world.headers(ana))
    assert [item["id"] for item in listed.json()["items"]] == [body["id"]]
    assert listed.json()["limit"] == 10

    off = await world.app.client.patch(
        f"{API}/me/job-alerts/{body['id']}",
        json={"is_active": False, "delivery": "digest"},
        headers=world.headers(ana),
    )
    assert off.status_code == 200, off.text
    assert (off.json()["is_active"], off.json()["delivery"]) == (False, "digest")
    radius = await world.app.client.patch(
        f"{API}/me/job-alerts/{body['id']}",
        json={
            "criteria": {
                "category_ids": [ids["leaf"]],
                "city_id": ids["city"],
                "center": {"lat": 45.245, "lon": 19.845},
                "radius_km": 3,
            }
        },
        headers=world.headers(ana),
    )
    assert radius.status_code == 200, radius.text
    assert radius.json()["criteria"]["radius_km"] == 3
    assert radius.json()["criteria"]["min_budget"] is None  # условия — целиком

    stranger = await world.user()
    # чужой ресурс (8.4): чужую подписку не изменить и не удалить
    foreign_patch = await world.app.client.patch(
        f"{API}/me/job-alerts/{body['id']}",
        json={"is_active": True},
        headers=world.headers(stranger),
    )
    assert (foreign_patch.status_code, foreign_patch.json()["code"]) == (404, "job_alert_not_found")
    foreign = await world.app.client.delete(
        f"{API}/me/job-alerts/{body['id']}", headers=world.headers(stranger)
    )
    assert foreign.status_code == 404
    assert foreign.json()["code"] == "job_alert_not_found"
    gone = await world.app.client.delete(
        f"{API}/me/job-alerts/{body['id']}", headers=world.headers(ana)
    )
    assert gone.status_code == 204
    listed = await world.app.client.get(f"{API}/me/job-alerts", headers=world.headers(ana))
    assert listed.json()["items"] == []

    for _ in range(10):
        await world.created(ana, category_ids=[ids["section"]], city_id=ids["city"])
    full = await world.create(ana, category_ids=[ids["section"]], city_id=ids["city"])
    assert full.status_code == 409
    assert full.json()["code"] == "job_alerts_full"


@pytest.mark.parametrize(
    "criteria",
    [
        {"category_ids": [999_999]},
        {"district_ids": [999_999]},
        {"center": {"lat": 45.25, "lon": 19.84}},
        {"category_ids": []},
    ],
)
async def test_alert_refuses_unknown_references(world: Alerts, criteria: dict[str, Any]) -> None:
    ids = await world.ids()
    ana = await world.user()

    reply = await world.create(
        ana, **({"category_ids": [ids["section"]], "city_id": ids["city"]} | criteria)
    )

    assert reply.status_code == 422, reply.text


async def test_new_job_reaches_matching_alerts_only(world: Alerts) -> None:
    """§9.6: раздел задевает подкатегорию заявки; районы, радиус от точки, бюджет «от»,
    срочность и язык — каждый отсекает своё; своя заявка, выключенная и на паузе — нет."""
    ids = await world.ids()
    client = await world.user("Елена")
    base = {"city_id": ids["city"], "category_ids": [ids["section"]]}
    liman = world.centers["liman-3"]
    people = {
        name: await world.user(name)
        for name in (
            "section",
            "leaf",
            "district",
            "radius",
            "budget_ok",
            "urgency_ok",
            "language",
            "other_category",
            "far_district",
            "far_radius",
            "too_cheap",
            "urgent_only",
            "english",
            "off",
            "paused",
        )
    }
    await world.created(people["section"], **base)
    await world.created(people["leaf"], **(base | {"category_ids": [ids["leaf"]]}))
    await world.created(people["district"], **(base | {"district_ids": [ids["liman"]]}))
    await world.created(
        people["radius"],
        **(base | {"center": {"lat": liman.lat, "lon": liman.lon}, "radius_km": 2}),
    )
    await world.created(people["budget_ok"], **(base | {"min_budget": 500_000}))
    await world.created(people["urgency_ok"], **(base | {"urgencies": ["this_week", "today"]}))
    await world.created(people["language"], **(base | {"languages": ["ru"]}))
    await world.created(people["other_category"], **(base | {"category_ids": [ids["other"]]}))
    await world.created(people["far_district"], **(base | {"district_ids": [ids["far"]]}))
    await world.created(
        people["far_radius"],
        **(base | {"center": {"lat": liman.lat + 0.2, "lon": liman.lon}, "radius_km": 3}),
    )
    await world.created(people["too_cheap"], **(base | {"min_budget": 500_001}))
    await world.created(people["urgent_only"], **(base | {"urgencies": ["asap"]}))
    await world.created(people["english"], **(base | {"languages": ["en"]}))
    off = await world.created(people["off"], **base)
    await world.app.client.patch(
        f"{API}/me/job-alerts/{off['id']}",
        json={"is_active": False},
        headers=world.headers(people["off"]),
    )
    await world.created(people["paused"], **base)
    await world.execute(
        "UPDATE jobs.alerts SET paused_until = now() + interval '1 day' WHERE user_id = :id",
        id=people["paused"],
    )
    await world.created(client, **base)  # своя заявка автору не приходит
    job_id = await world.job(client)
    await world.execute("UPDATE jobs.jobs SET languages = '{ru}' WHERE id = :id", id=job_id)

    matched = await world.match(job_id)

    expected = {"section", "leaf", "district", "radius", "budget_ok", "urgency_ok", "language"}
    cards = await world.matched(job_id)
    assert {name for name, user in people.items() if str(user) in cards} == expected
    assert matched == len(expected)
    assert cards[str(people["radius"])]["distance_m"] == 100
    assert cards[str(people["section"])]["distance_m"] is None
    assert await world.scalar(
        "SELECT notified_count FROM jobs.jobs WHERE id = :id", id=job_id
    ) == len(expected)

    again = await world.match(job_id)  # повтор задачи — без вторых карточек
    assert again == 0
    assert len(await world.matched(job_id)) == len(expected)


async def test_blocked_and_restricted_people_get_no_card(world: Alerts) -> None:
    ids = await world.ids()
    client = await world.user("Елена")
    base = {"city_id": ids["city"], "category_ids": [ids["section"]]}
    people = {name: await world.user(name) for name in ("blocked", "blocker", "restricted", "fine")}
    for user in people.values():
        await world.created(user, **base)
    await world.execute(
        "INSERT INTO identity.user_blocks (blocker_id, blocked_id) VALUES (:a, :b), (:c, :d)",
        a=client,
        b=people["blocked"],
        c=people["blocker"],
        d=client,
    )
    async with world.app.container() as request:
        await insert_restriction(
            await request.get(AsyncSession), people["restricted"], "responding_blocked"
        )
    job_id = await world.job(client)

    await world.match(job_id)

    assert set(await world.matched(job_id)) == {str(people["fine"])}


async def test_card_parameters_on_the_recipient_language(world: Alerts) -> None:
    ids = await world.ids()
    client = await world.user("Елена")
    ana = await world.user("Ana")
    await world.execute("UPDATE identity.users SET ui_locale = 'sr-Latn' WHERE id = :id", id=ana)
    alert = await world.created(
        ana, city_id=ids["city"], category_ids=[ids["section"], ids["other"]]
    )
    template = await world.template(ana, "Mogu danas")
    job_id = await world.job(client)
    await world.match(job_id)

    sent = await run_queued(world.app.container, MATCHED, user_id=ana)

    assert sent == 1
    [notice] = await world.rows(
        "SELECT payload, dedupe_key FROM notifications.notifications WHERE user_id = :id"
        " AND type = 'job.matched'",
        id=ana,
    )
    params = notice["payload"]["params"]
    assert notice["dedupe_key"] == f"job.matched:{job_id}:{ana}"
    assert params["title"] == "Повесить люстру"
    assert (params["budget_type"], params["budget_min"]) == ("fixed", "500000")
    assert params["district"] == "Liman 3"
    assert params["alert_id"] == alert["id"]
    assert params["alert_more"] == "1"
    assert params["alert"] == "Majstor za kućne popravke"  # на латинице получателя
    assert params["template_0"] == template.json()["id"]
    assert (params["responses"], params["max_responses"]) == ("0", "5")
    assert notice["payload"]["link"].startswith("j_")


async def test_closed_job_or_own_response_send_nothing(world: Alerts) -> None:
    ids = await world.ids()
    client = await world.user("Елена")
    ana, bob = await world.user("Ana"), await world.user("Bob")
    for user in (ana, bob):
        await world.created(user, city_id=ids["city"], category_ids=[ids["section"]])
    job_id = await world.job(client)
    await world.match(job_id)
    await world.responded(bob, job_id)  # откликнулся из ленты, пока карточка ждала
    await world.execute("UPDATE jobs.jobs SET status = 'closed' WHERE id = :id", id=job_id)

    await run_queued(world.app.container, MATCHED, user_id=ana)
    await run_queued(world.app.container, MATCHED, user_id=bob)

    assert (
        await world.rows(
            "SELECT id FROM notifications.notifications WHERE user_id IN (:a, :b)", a=ana, b=bob
        )
        == []
    )


async def test_frequency_limit_sends_the_rest_to_the_digest(world: Alerts) -> None:
    ids = await world.ids()
    client = await world.user("Елена")
    ana = await world.user("Ana")
    await world.created(ana, city_id=ids["city"], category_ids=[ids["section"]])
    jobs = [await world.job(client) for _ in range(11)]

    for job_id in jobs:
        await world.match(job_id)

    rows = await world.rows(
        "SELECT job_id, delivery FROM jobs.alert_matches WHERE user_id = :id ORDER BY created_at",
        id=ana,
    )
    assert [row["delivery"] for row in rows] == ["instant"] * 10 + ["digest"]


class DueEveryone:
    async def due(self, user_ids: Collection[UserId], at: datetime) -> frozenset[UserId]:
        return frozenset(user_ids)


class DueNobody:
    async def due(self, user_ids: Collection[UserId], at: datetime) -> frozenset[UserId]:
        return frozenset()


async def test_digest_goes_out_in_the_digest_hour(world: Alerts) -> None:
    ids = await world.ids()
    client = await world.user("Елена")
    ana = await world.user("Ana")
    alert = await world.created(
        ana, delivery="digest", city_id=ids["city"], category_ids=[ids["section"]]
    )
    jobs = [await world.job(client) for _ in range(2)]
    for job_id in jobs:
        await world.match(job_id)
    assert await world.matched(jobs[0]) == {}  # подборка — не карточка B1

    async def digests(schedule: object) -> int:
        async with world.app.container() as request:
            send = SendAlertDigests(
                await request.get(UnitOfWork),
                await request.get(AlertMatches),
                schedule,  # type: ignore[arg-type]
                await request.get(JobQueue),
                FakeClock(datetime.now(UTC) + timedelta(minutes=1)),
            )
            return await send(SendAlertDigestsCommand())

    assert await digests(DueNobody()) == 0  # не его час — ждёт
    assert await digests(DueEveryone()) >= 1
    sent = await run_queued(world.app.container, DIGEST, user_id=ana)
    assert sent == 1
    [notice] = await world.rows(
        "SELECT payload FROM notifications.notifications WHERE user_id = :id"
        " AND type = 'job.digest'",
        id=ana,
    )
    assert notice["payload"]["params"]["alert_0_count"] == "2"
    assert notice["payload"]["link"] == "m_feed"
    assert (
        await world.rows(
            "SELECT job_id FROM jobs.alert_matches WHERE alert_id = :id AND digested_at IS NULL",
            id=alert["id"],
        )
        == []
    )


async def test_feed_by_my_alerts(world: Alerts) -> None:
    ids = await world.ids()
    client = await world.user("Елена")
    ana = await world.user("Ana")
    await world.created(ana, city_id=ids["city"], category_ids=[ids["section"]], min_budget=600_000)
    cheap = await world.job(client)
    rich = await world.job(client)
    await world.execute("UPDATE jobs.jobs SET budget_min = 700000 WHERE id = :id", id=rich)

    mine = await world.app.client.get(
        f"{API}/jobs",
        params={"city_id": ids["city"], "feed": "alerts"},
        headers=world.headers(ana),
    )
    counted = await world.app.client.get(
        f"{API}/jobs/count",
        params={"city_id": ids["city"], "feed": "alerts"},
        headers=world.headers(ana),
    )
    guest = await world.app.client.get(
        f"{API}/jobs", params={"city_id": ids["city"], "feed": "alerts"}
    )

    found = {item["id"] for item in mine.json()["items"]}
    assert str(rich) in found
    assert str(cheap) not in found
    assert counted.json()["count"] == len(found)
    assert guest.status_code == 401


async def test_account_deletion_forgets_alerts_and_matches(world: Alerts) -> None:
    ids = await world.ids()
    client = await world.user("Елена")
    ana = await world.user("Ana")
    await world.created(ana, city_id=ids["city"], category_ids=[ids["section"]])
    await world.match(await world.job(client))

    async with world.app.container() as request:
        forget = await request.get(ForgetAlerts)
        await forget(ForgetAlertsCommand(user_id=ana))

    assert await world.rows("SELECT id FROM jobs.alerts WHERE user_id = :id", id=ana) == []
    assert (
        await world.rows("SELECT job_id FROM jobs.alert_matches WHERE user_id = :id", id=ana) == []
    )


async def test_stale_profile_is_reminded_once_in_two_weeks(world: Alerts) -> None:
    async def profile(*, updated_days_ago: int, available: bool = False) -> UserId:
        user = await world.user()
        await world.execute(
            "INSERT INTO specialists.profiles (id, user_id, kind, status, display_name, city_id,"
            " created_at, updated_at, published_at, available_until, version)"
            " SELECT :id, :user, 'pro', 'published', 'Ana', c.id, now(),"
            " now() - make_interval(days => :days), now(), :until, 1"
            " FROM geo.cities c WHERE c.slug = 'novi-sad'",
            id=new_id(),
            user=user,
            days=updated_days_ago,
            until=datetime.now(UTC) + timedelta(hours=3) if available else None,
        )
        return user

    stale = await profile(updated_days_ago=40)
    fresh = await profile(updated_days_ago=3)
    available = await profile(updated_days_ago=40, available=True)
    before = await world.scalar(
        "SELECT updated_at FROM specialists.profiles WHERE user_id = :id", id=stale
    )

    async def remind() -> None:
        async with world.app.container() as request:
            remind = await request.get(RemindStaleProfiles)
            await remind(RemindStaleProfilesCommand(any_hour=True))

    await remind()
    await remind()  # второй раз за две недели — тишина

    queued = await world.rows(
        "SELECT args->'payload'->>'user_id' AS user_id FROM procrastinate_jobs"
        " WHERE task_name = 'notifications.notify_profile_stale' AND status = 'todo'"
        " AND args->'payload'->>'user_id' IN (:a, :b, :c)",
        a=str(stale),
        b=str(fresh),
        c=str(available),
    )
    assert [row["user_id"] for row in queued] == [str(stale)]
    assert (
        await world.scalar(
            "SELECT updated_at FROM specialists.profiles WHERE user_id = :id", id=stale
        )
        == before
    )  # отметка напоминания — не правка профиля
    assert (
        await run_queued(world.app.container, "notifications.notify_profile_stale", user_id=stale)
        == 1
    )
    [notice] = await world.rows(
        "SELECT payload FROM notifications.notifications WHERE user_id = :id"
        " AND type = 'profile.stale_reminder'",
        id=stale,
    )
    assert notice["payload"]["link"] == "m_availability"


async def test_republished_job_reaches_only_new_subscribers(world: Alerts) -> None:
    """Продление истёкшей заявки — снова JobPublished (`republished`): подписавшийся после первой
    публикации получает карточку, кто получал — второй не получает."""
    ids = await world.ids()
    client = await world.user("Елена")
    base = {"city_id": ids["city"], "category_ids": [ids["section"]]}
    early, late = await world.user("early"), await world.user("late")
    await world.created(early, **base)
    job_id = await world.job(client)
    assert await world.match(job_id) == 1

    await world.created(late, **base)
    await world.execute("UPDATE jobs.jobs SET status = 'expired' WHERE id = :id", id=job_id)
    async with world.app.container() as request:
        extend = await request.get(ExtendJob)
        await extend(ExtendJobCommand(actor_id=client, job_id=JobId(job_id)))
    assert (
        await run_queued(world.app.container, "jobs.match_alerts", user_id=client, by="client_id")
        == 1
    )

    assert set(await world.matched(job_id)) == {str(early), str(late)}
    assert (
        await world.scalar("SELECT count(*) FROM jobs.alert_matches WHERE job_id = :id", id=job_id)
        == 2
    )
    assert await world.scalar("SELECT notified_count FROM jobs.jobs WHERE id = :id", id=job_id) == 2


async def test_new_alert_catches_up_open_jobs_of_the_last_days(world: Alerts) -> None:
    """Досыл новой подписке: открытые заявки последних трёх суток — карточками в лимит частоты,
    остальное в подборку; старше трёх суток, без мест, своя и заблокированного — нет."""
    ids = await world.ids()
    client, enemy, ana = (
        await world.user("Елена"),
        await world.user("Враг"),
        await world.user("Ana"),
    )
    fresh = [await world.job(client) for _ in range(INSTANT_PER_HOUR + 2)]
    old = await world.job(client)
    await world.execute(
        "UPDATE jobs.jobs SET published_at = now() - interval '4 days' WHERE id = :id", id=old
    )
    full = await world.job(client, max_responses=1)
    await world.execute("UPDATE jobs.jobs SET responses_count = 1 WHERE id = :id", id=full)
    blocked = await world.job(enemy)
    await world.execute(
        "INSERT INTO identity.user_blocks (blocker_id, blocked_id) VALUES (:a, :b)", a=ana, b=enemy
    )
    own = await world.job(ana)

    body = await world.created(ana, city_id=ids["city"], category_ids=[ids["section"]])
    assert await run_queued(world.app.container, "jobs.catch_up_alert", user_id=ana) == 1

    rows = await world.rows(
        "SELECT job_id, delivery FROM jobs.alert_matches WHERE user_id = :id", id=ana
    )
    by_job = {row["job_id"]: row["delivery"] for row in rows}
    # данные тестов коммитятся: подошли и свежие заявки соседних тестов — это не ошибка
    assert set(fresh) <= set(by_job)
    assert not {old, full, blocked, own} & set(by_job)
    instant = {job_id for job_id, delivery in by_job.items() if delivery == "instant"}
    assert len(instant) == INSTANT_PER_HOUR
    assert len(by_job) - len(instant) >= 2
    cards = await world.rows(
        "SELECT args->'payload'->>'job_id' AS job_id FROM procrastinate_jobs"
        " WHERE task_name = :task AND args->'payload'->>'user_id' = :user",
        task=MATCHED,
        user=str(ana),
    )
    assert {row["job_id"] for row in cards} == {str(job_id) for job_id in instant}
    assert (
        await world.scalar("SELECT notified_count FROM jobs.jobs WHERE id = :id", id=fresh[0]) == 1
    )
    async with world.app.container() as request:  # повтор задачи — ничего нового
        catch_up = await request.get(CatchUpAlert)
        assert await catch_up(CatchUpAlertCommand(alert_id=AlertId(UUID(body["id"])))) == 0


async def test_published_profile_gets_an_alert_once(world: Alerts) -> None:
    """Первая публикация профиля — подписка по его категориям и районам, без своих действий
    исполнителя; за ней — досыл; повтор публикации и свои подписки — ничего."""
    specialist = Specialist(world.app.container)
    await specialist.publish()
    world.users.append(specialist.user_id)
    client = await world.user("Елена")
    job_id = await world.job(client)
    # заявка по услуге и в районе профиля: её досыл подтвердит, что подписка — по профилю
    await world.execute(
        "UPDATE jobs.jobs SET category_id = :category, district_id = :district,"
        " category_path = (SELECT path FROM catalog.categories WHERE id = :category)"
        " WHERE id = :id",
        id=job_id,
        category=specialist.category,
        district=specialist.district,
    )

    assert (
        await run_queued(
            world.app.container, "jobs.create_profile_alert", user_id=specialist.user_id
        )
        == 1
    )

    listed = await world.app.client.get(
        f"{API}/me/job-alerts", headers=world.headers(specialist.user_id)
    )
    [alert] = listed.json()["items"]
    assert alert["delivery"] == "instant"
    assert alert["is_active"] is True
    assert alert["criteria"]["category_ids"] == [specialist.category]
    assert alert["criteria"]["city_id"] == specialist.city
    assert alert["criteria"]["district_ids"] == [specialist.district]
    assert alert["criteria"]["min_budget"] is None
    assert (
        await run_queued(world.app.container, "jobs.catch_up_alert", user_id=specialist.user_id)
        == 1
    )
    assert str(specialist.user_id) in await world.matched(job_id)

    async with world.app.container() as request:  # повторная публикация профиля
        create = await request.get(CreateProfileAlert)
        again = await create(
            CreateProfileAlertCommand(user_id=specialist.user_id, profile_id=specialist.profile_id)
        )
    assert again is None
    assert (
        await world.scalar(
            "SELECT count(*) FROM jobs.alerts WHERE user_id = :id", id=specialist.user_id
        )
        == 1
    )
    await specialist.drop_jobs()
