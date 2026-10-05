"""Отклики (DEVELOPMENT_PLAN 5.4) через API и конвейер модерации: исполнитель откликается на
опубликованную заявку, текст уходит на проверку — клиент видит отклик после неё (чистый — сразу,
с контактами — после решения модератора); на свою, закрытую и полную заявку — 409 со своим кодом;
десять параллельных откликов на пять мест дают ровно пять; правка отклика увеличивает версию
заявки; суточный лимит по уровню доверия — 429 на своей границе; «Мои отклики» с группами и
квотой дня; удалённый аккаунт отзывает свои отклики; три отклика за окно — одно уведомление
клиенту «Новых откликов: 3». Шаблоны откликов (5.5): не больше двух и под гонкой, первый —
основной, «сделать основным» и удаление сдвигают порядок, чужой — 404; отклик из шаблона хранит
его id, а карточка заявки показывает исполнителю его отклик. Данные коммитятся.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_worker_container, module_routers
from app.entrypoints.seeds import load_city_seeds
from app.modules.jobs.application.use_cases.forget_client_jobs import (
    ForgetClientJobs,
    ForgetClientJobsCommand,
)
from app.modules.jobs.application.use_cases.withdraw_performer_responses import (
    WithdrawPerformerResponses,
    WithdrawPerformerResponsesCommand,
)
from app.modules.moderation.application.use_cases.auto_check import AutoCheck, AutoCheckCommand
from app.modules.moderation.application.use_cases.decide_case import (
    DecideCase,
    DecideCaseCommand,
)
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.pipeline import Route, Routing
from app.modules.moderation.errors import CaseSupersededError
from app.platform.contracts.events.moderation import ModerationDecision
from app.platform.kernel.ids import UserId, new_id
from app.platform.ratelimit import Rate
from app.platform.settings import Settings
from tests.plugins.http import HttpApp, bearer, http_app
from tests.plugins.identity import accept_rules, insert_user
from tests.plugins.queue import run_queued

pytestmark = pytest.mark.integration

API = "/api/v1"


@pytest.fixture
async def web(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[HttpApp]:
    ip = f"10.{new_id().int % 250}.{new_id().int % 250}.{new_id().int % 250}"
    async with http_app(storage_settings, *module_routers(), client_ip=ip) as app:
        yield app


@pytest.fixture
async def worker(storage_settings: Settings) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(storage_settings)
    try:
        yield container
    finally:
        await container.close()


def unique(text_: str) -> str:
    """Текст с меткой теста: один текст от трёх аккаунтов за сутки velocity считает рассылкой."""
    mark = "".join(chr(ord("a") + int(digit, 16)) for digit in new_id().hex[-10:])
    return f"{text_} Метка {mark}."


class World:
    def __init__(self, app: HttpApp, settings: Settings) -> None:
        self.app, self.settings = app, settings
        self.users: list[UserId] = []
        self.centers = {d.slug: d.center for s in load_city_seeds() for d in s.districts}

    async def scalar(self, sql: str, **params: object) -> Any:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar()

    async def execute(self, sql: str, **params: object) -> None:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)

    async def user(self, name: str = "Марко") -> UserId:
        async with self.app.container() as request:
            session = await request.get(AsyncSession)
            user_id = await insert_user(session)
            await accept_rules(session, user_id)
        await self.execute(
            "UPDATE identity.users SET display_name = :name WHERE id = :id", name=name, id=user_id
        )
        self.users.append(user_id)
        return user_id

    async def job(
        self, client_id: UserId, *, status: str = "published", max_responses: int = 5
    ) -> UUID:
        """Опубликованная заявка строкой: модерация заявки этим тестам не нужна."""
        job_id = new_id()
        category = await self.scalar(
            "SELECT min(id) FROM catalog.categories WHERE is_active AND jobs_enabled"
            " AND risk_level = 0 AND parent_id IS NOT NULL"
        )
        path = await self.scalar("SELECT path FROM catalog.categories WHERE id = :id", id=category)
        center = self.centers["liman-3"]
        now = datetime.now(UTC)
        await self.execute(
            "INSERT INTO jobs.jobs (id, client_id, status, title, description, content_lang,"
            " category_id, category_path, urgency, budget_type, budget_min, city_id,"
            " district_id, point_public, max_responses, published_at, expires_at, version)"
            " VALUES (:id, :client, :status, 'Повесить люстру', 'Люстра на пять рожков', 'ru',"
            " :category, :path, 'this_week', 'fixed', 500000,"
            " (SELECT id FROM geo.cities WHERE slug = 'novi-sad'),"
            " (SELECT id FROM geo.districts WHERE slug = 'liman-3'),"
            " ST_GeogFromText(:point), :max_responses, :published, :expires, 1)",
            id=job_id,
            client=client_id,
            status=status,
            category=category,
            path=list(path),
            point=f"SRID=4326;POINT({center.lon} {center.lat})",
            max_responses=max_responses,
            published=now - timedelta(minutes=30) if status == "published" else None,
            expires=now + timedelta(days=7),
        )
        return job_id

    def headers(self, user_id: UserId, *, trust_level: int = 0) -> dict[str, str]:
        return bearer(self.settings, user_id, trust_level=trust_level)

    async def respond(
        self,
        performer: UserId,
        job_id: UUID,
        *,
        message: str | None = None,
        trust_level: int = 0,
        price: dict[str, Any] | None = None,
        template_id: str | None = None,
    ) -> httpx.Response:
        body = {
            "message": message or unique("Здравствуйте! Могу сегодня в 19:00, свой инструмент."),
            **(price or {"price_type": "fixed", "price_amount": 350_000}),
            "availability_note": "Сегодня, 19:00",
            "template_id": template_id,
        }
        headers = self.headers(performer, trust_level=trust_level) | {
            "Idempotency-Key": new_id().hex
        }
        return await self.app.client.post(
            f"{API}/jobs/{job_id}/responses", json=body, headers=headers
        )

    async def responded(self, performer: UserId, job_id: UUID, **kwargs: Any) -> dict[str, Any]:
        reply = await self.respond(performer, job_id, **kwargs)
        assert reply.status_code == 201, reply.text
        body: dict[str, Any] = reply.json()
        return body

    async def template(self, performer: UserId, title: str, **offer: Any) -> httpx.Response:
        body = {
            "title": title,
            "message": unique("Здравствуйте! Могу сегодня вечером, инструмент свой."),
            "price_type": "fixed",
            "price_amount": 300_000,
        } | offer
        headers = self.headers(performer) | {"Idempotency-Key": new_id().hex}
        return await self.app.client.post(
            f"{API}/me/response-templates", json=body, headers=headers
        )

    async def templates(self, performer: UserId) -> list[str]:
        """Id шаблонов по порядку; первый — основной."""
        reply = await self.app.client.get(
            f"{API}/me/response-templates", headers=self.headers(performer)
        )
        assert reply.status_code == 200, reply.text
        body = reply.json()
        assert body["limit"] == 2
        assert [t["primary"] for t in body["items"]] == [n == 0 for n in range(len(body["items"]))]
        return [t["id"] for t in body["items"]]

    async def owner_list(self, client: UserId, job_id: UUID) -> list[dict[str, Any]]:
        reply = await self.app.client.get(
            f"{API}/jobs/{job_id}/responses", headers=self.headers(client)
        )
        assert reply.status_code == 200, reply.text
        items: list[dict[str, Any]] = reply.json()["items"]
        return items

    async def job_row(self, job_id: UUID) -> tuple[int, int]:
        """Версия заявки и число активных откликов."""
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT version, responses_count FROM jobs.jobs WHERE id = :id"),
                    {"id": job_id},
                )
            ).one()
        return int(row[0]), int(row[1])


@pytest.fixture
async def world(web: HttpApp, storage_settings: Settings) -> AsyncIterator[World]:
    """Пользователи теста; их задачи в очереди (проверка текста, события) тест не выполняет."""
    created = World(web, storage_settings)
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


async def auto_check(worker: AsyncContainer, performer: UserId, response_id: str) -> Routing:
    async with worker() as request:
        routing = await (await request.get(AutoCheck))(
            AutoCheckCommand(
                entity_type=EntityType.RESPONSE,
                entity_id=UUID(response_id),
                author_id=performer,
            )
        )
    assert routing is not None
    return routing


@pytest.mark.authz
async def test_clean_response_is_shown_to_the_owner_after_the_check(
    world: World, worker: AsyncContainer
) -> None:
    client, performer = await world.user("Елена К."), await world.user("Марко П.")
    job_id = await world.job(client)

    response = await world.responded(performer, job_id)

    assert (response["status"], response["review"], response["is_first"]) == (
        "submitted",
        "pending",
        True,
    )
    assert response["price"] == {
        "type": "fixed",
        "amount": {"amount": 350_000, "currency": "RSD"},
    }
    assert response["job"]["id"] == str(job_id)
    assert response["job"]["responses_count"] == 1
    assert await world.owner_list(client, job_id) == []  # на проверке — клиенту не видно

    routing = await auto_check(worker, performer, response["id"])

    assert routing.route is Route.PUBLISH
    [listed] = await world.owner_list(client, job_id)
    assert listed["id"] == response["id"]
    assert listed["performer"]["display_name"] == "Марко П."
    assert listed["is_first"] is True
    assert listed["availability_note"] == "Сегодня, 19:00"
    stranger = await world.user()
    other = await world.app.client.get(
        f"{API}/jobs/{job_id}/responses", headers=world.headers(stranger)
    )
    assert (other.status_code, other.json()["code"]) == (404, "job_not_found")


async def test_response_with_contacts_waits_for_a_moderator(
    world: World, worker: AsyncContainer
) -> None:
    client, performer = await world.user(), await world.user()
    job_id = await world.job(client)
    leaking = unique("Здравствуйте! Звоните: +381 64 123 4567, приеду сегодня.")
    response = await world.responded(performer, job_id, message=leaking)

    routing = await auto_check(worker, performer, response["id"])

    assert routing.route is Route.REVIEW
    assert await world.owner_list(client, job_id) == []
    case_id = await world.scalar(
        "SELECT id FROM moderation.cases WHERE entity_id = :id AND status = 'pending'",
        id=UUID(response["id"]),
    )
    async with worker() as request:
        await (await request.get(DecideCase))(
            DecideCaseCommand(
                case_id=case_id, verdict=ModerationDecision.REJECTED, reason_code="contact_leak"
            )
        )
    mine = await world.app.client.get(f"{API}/me/responses", headers=world.headers(performer))
    [blocked] = mine.json()["items"]
    assert (blocked["review"], blocked["status"]) == ("blocked", "withdrawn")
    assert await world.job_row(job_id) == (3, 0)  # место освободилось
    assert await world.owner_list(client, job_id) == []


async def test_moderator_clears_only_the_offer_the_card_showed(
    world: World, worker: AsyncContainer
) -> None:
    """ADV-11: отклик с телефоном ждёт модератора; исполнитель меняет текст после карточки.
    Одобрение прежней карточки ничего не показывает клиенту — кейс устарел; новый кейс о правке
    одобряют — клиент видит ровно её."""
    client, performer = await world.user(), await world.user()
    job_id = await world.job(client)
    leaking = unique("Здравствуйте! Звоните: +381 64 123 4567, приеду сегодня.")
    response = await world.responded(performer, job_id, message=leaking)
    assert (await auto_check(worker, performer, response["id"])).route is Route.REVIEW
    pending = "SELECT id FROM moderation.cases WHERE entity_id = :id AND status = 'pending'"
    stale_case = await world.scalar(pending, id=UUID(response["id"]))
    swapped = unique("Пишите в телеграм @qa_contact_test, так быстрее.")

    revised = await world.app.client.patch(
        f"{API}/responses/{response['id']}",
        json={"message": swapped, "price_type": "negotiable"},
        headers=world.headers(performer),
    )
    assert revised.status_code == 200, revised.text
    await auto_check(worker, performer, response["id"])
    with pytest.raises(CaseSupersededError):
        async with worker() as request:
            await (await request.get(DecideCase))(
                DecideCaseCommand(case_id=stale_case, verdict=ModerationDecision.APPROVED)
            )

    assert await world.owner_list(client, job_id) == []
    fresh_case = await world.scalar(pending, id=UUID(response["id"]))
    assert fresh_case not in (None, stale_case)
    async with worker() as request:
        await (await request.get(DecideCase))(
            DecideCaseCommand(case_id=fresh_case, verdict=ModerationDecision.APPROVED)
        )
    [listed] = await world.owner_list(client, job_id)
    assert (listed["id"], listed["message"]) == (response["id"], swapped)


@pytest.mark.authz
async def test_responding_refuses_own_full_closed_and_repeated(world: World) -> None:
    client, performer = await world.user(), await world.user()
    job_id = await world.job(client, max_responses=1)
    hidden = await world.job(client, status="pending_moderation")

    own = await world.respond(client, job_id)
    first = await world.respond(performer, job_id)
    again = await world.respond(performer, job_id)
    late = await world.respond(await world.user(), job_id)
    unpublished = await world.respond(performer, hidden)
    unknown = await world.respond(performer, new_id())

    assert (own.status_code, own.json()["code"]) == (409, "own_job")
    assert first.status_code == 201, first.text
    assert (again.status_code, again.json()["code"]) == (409, "already_responded")
    assert (late.status_code, late.json()["code"], late.json()["limit"]) == (409, "job_full", 1)
    assert (unpublished.status_code, unpublished.json()["code"]) == (404, "job_not_found")
    assert (unknown.status_code, unknown.json()["code"]) == (404, "job_not_found")
    invalid = await world.respond(
        await world.user(), job_id, price={"price_type": "negotiable", "price_amount": 100}
    )
    assert (invalid.status_code, invalid.json()["code"]) == (422, "invalid_response")
    guest = await world.app.client.post(
        f"{API}/jobs/{job_id}/responses",
        json={"message": "Привет", "price_type": "negotiable"},
        headers={"Idempotency-Key": new_id().hex},
    )
    assert guest.status_code == 401


async def test_ten_parallel_responses_take_exactly_five_places(world: World) -> None:
    client = await world.user()
    job_id = await world.job(client)
    performers = [await world.user() for _ in range(10)]

    replies = await asyncio.gather(*(world.respond(p, job_id) for p in performers))

    codes = sorted(reply.status_code for reply in replies)
    assert codes == [201] * 5 + [409] * 5
    assert {r.json()["code"] for r in replies if r.status_code == 409} == {"job_full"}
    version, count = await world.job_row(job_id)
    assert (count, version) == (5, 6)  # каждый отклик — новая версия заявки
    stored = await world.scalar("SELECT count(*) FROM jobs.responses WHERE job_id = :id", id=job_id)
    assert stored == 5


@pytest.mark.authz
async def test_revising_and_withdrawing_bump_the_job_version(world: World) -> None:
    client, performer = await world.user(), await world.user()
    job_id = await world.job(client)
    response = await world.responded(performer, job_id)
    assert await world.job_row(job_id) == (2, 1)
    headers = world.headers(performer)

    revised = await world.app.client.patch(
        f"{API}/responses/{response['id']}",
        json={"message": unique("Могу завтра утром."), "price_type": "negotiable"},
        headers=headers,
    )

    assert revised.status_code == 200, revised.text
    assert (revised.json()["price"], revised.json()["review"]) == (
        {"type": "negotiable", "amount": None},
        "pending",
    )
    assert await world.job_row(job_id) == (3, 1)  # правка отклика — новая версия заявки
    shown = await world.app.client.get(f"{API}/responses/{response['id']}", headers=headers)
    assert (shown.status_code, shown.json()["message"]) == (200, revised.json()["message"])
    assert shown.json()["job"]["id"] == str(job_id)
    withdrawn = await world.app.client.post(
        f"{API}/responses/{response['id']}/withdraw", headers=headers
    )
    assert (withdrawn.status_code, withdrawn.json()["status"]) == (200, "withdrawn")
    assert await world.job_row(job_id) == (4, 0)
    twice = await world.app.client.post(
        f"{API}/responses/{response['id']}/withdraw", headers=headers
    )
    assert (twice.status_code, twice.json()["code"]) == (409, "response_not_active")
    again = await world.respond(performer, job_id)
    assert (again.status_code, again.json()["code"]) == (409, "already_responded")
    stranger = await world.app.client.post(
        f"{API}/responses/{response['id']}/withdraw", headers=world.headers(await world.user())
    )
    assert (stranger.status_code, stranger.json()["code"]) == (404, "response_not_found")
    peeked = await world.app.client.get(
        f"{API}/responses/{response['id']}", headers=world.headers(client)
    )
    assert (peeked.status_code, peeked.json()["code"]) == (404, "response_not_found")


async def test_my_responses_have_groups_and_the_daily_quota(world: World) -> None:
    client, performer = await world.user(), await world.user()
    jobs = [await world.job(client) for _ in range(3)]
    responses = [await world.responded(performer, job_id) for job_id in jobs]
    headers = world.headers(performer)
    await world.app.client.post(f"{API}/responses/{responses[0]['id']}/withdraw", headers=headers)
    await world.app.client.post(
        f"{API}/jobs/{jobs[1]}/close", json={"reason": "not_needed"}, headers=world.headers(client)
    )

    everything = await world.app.client.get(f"{API}/me/responses", headers=headers)
    active = await world.app.client.get(
        f"{API}/me/responses", params={"status": "active"}, headers=headers
    )

    assert everything.status_code == 200, everything.text
    body = everything.json()
    assert [item["id"] for item in body["items"]] == [r["id"] for r in reversed(responses)]
    assert body["counts"] == {
        "all": 3,
        "active": 1,
        "accepted": 0,
        "not_selected": 1,
        "archive": 1,
    }
    assert body["today"] == {"used": 3, "limit": 10}
    assert [item["id"] for item in active.json()["items"]] == [responses[2]["id"]]
    closed = next(item for item in body["items"] if item["job"]["id"] == str(jobs[1]))
    assert (closed["status"], closed["job"]["status"]) == ("not_selected", "closed")


async def test_daily_limit_depends_on_trust_level(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    quota = "app.modules.jobs.infrastructure.quota"
    monkeypatch.setattr(f"{quota}.RESPONSES", Rate("jobs.responses_per_day", "2/day"))
    monkeypatch.setattr(
        f"{quota}.RESPONSES_TRUSTED", Rate("jobs.responses_per_day_trusted", "3/day")
    )
    client = await world.user()
    jobs = [await world.job(client) for _ in range(4)]
    newbie, trusted = await world.user(), await world.user()

    newbie_codes = [(await world.respond(newbie, job_id)).status_code for job_id in jobs[:3]]
    trusted_codes = [
        (await world.respond(trusted, job_id, trust_level=2)).status_code for job_id in jobs
    ]

    assert newbie_codes == [201, 201, 429]
    assert trusted_codes == [201, 201, 201, 429]
    refused = await world.respond(newbie, jobs[3])
    assert (refused.json()["code"], "Retry-After" in refused.headers) == (
        "daily_responses_limit",
        True,
    )
    full = await world.respond(await world.user(), await world.job(client, max_responses=0))
    assert full.json()["code"] == "job_full"  # отказ «мест нет» квоту не тратит


async def test_deleted_performer_responses_are_withdrawn(
    world: World, worker: AsyncContainer
) -> None:
    client, performer = await world.user(), await world.user()
    job_id = await world.job(client)
    response = await world.responded(performer, job_id)

    async with worker() as request:
        withdrawn = await (await request.get(WithdrawPerformerResponses))(
            WithdrawPerformerResponsesCommand(user_id=performer)
        )

    assert withdrawn == 1
    status = await world.scalar(
        "SELECT status FROM jobs.responses WHERE id = :id", id=UUID(response["id"])
    )
    assert status == "withdrawn"
    assert (await world.job_row(job_id))[1] == 0


async def test_three_responses_in_a_window_make_one_notice(
    world: World, worker: AsyncContainer
) -> None:
    client = await world.user("Елена К.")
    job_id = await world.job(client)
    performers = [await world.user() for _ in range(3)]
    responses = [await world.responded(performer, job_id) for performer in performers]

    scheduled = await run_queued(
        world.app.container,
        "notifications.schedule_responses_notice",
        user_id=job_id,
        by="job_id",
    )

    assert scheduled == 3
    waiting = await world.scalar(
        "SELECT count(*) FROM procrastinate_jobs WHERE task_name = 'notifications.notify_responses'"
        " AND status = 'todo' AND args->'payload'->>'job_id' = :job",
        job=str(job_id),
    )
    assert waiting == 1  # окно одно: замок очереди по заявке
    scheduled_at = await world.scalar(
        "SELECT scheduled_at FROM procrastinate_jobs WHERE task_name ="
        " 'notifications.notify_responses' AND args->'payload'->>'job_id' = :job",
        job=str(job_id),
    )
    assert scheduled_at > datetime.now(UTC) + timedelta(minutes=4)
    for performer, response in zip(performers, responses, strict=True):
        assert (await auto_check(worker, performer, response["id"])).route is Route.PUBLISH

    sent = await run_queued(
        world.app.container, "notifications.notify_responses", user_id=job_id, by="job_id"
    )

    assert sent == 1
    engine = await world.app.container.get(AsyncEngine)
    async with engine.connect() as conn:
        notices = (
            await conn.execute(
                text(
                    "SELECT payload->'params'->>'count', payload->>'link' FROM"
                    " notifications.notifications WHERE user_id = :user"
                    " AND type = 'response.received'"
                ),
                {"user": client},
            )
        ).all()
    assert [count for count, _ in notices] == ["3"]
    assert notices[0][1].startswith("j_")


@pytest.mark.authz
async def test_templates_are_two_at_most_and_the_first_is_primary(world: World) -> None:
    performer, stranger = await world.user(), await world.user()
    first = await world.template(performer, "Могу сегодня")
    second = await world.template(
        performer,
        "  На неделе  ",
        price_type="negotiable",
        price_amount=None,
        availability_note="На неделе",
    )
    third = await world.template(performer, "Ещё один")
    blank = await world.template(stranger, "   ")
    priced = await world.template(stranger, "Договорная", price_type="negotiable")

    assert (first.status_code, second.status_code) == (201, 201), second.text
    assert (first.json()["primary"], second.json()["primary"]) == (True, False)
    assert second.json()["title"] == "На неделе"
    assert second.json()["price"] == {"type": "negotiable", "amount": None}
    assert (third.status_code, third.json()["code"], third.json()["limit"]) == (
        409,
        "response_templates_full",
        2,
    )
    assert (blank.status_code, blank.json()["code"]) == (422, "invalid_response_template")
    assert (priced.status_code, priced.json()["code"], priced.json()["field"]) == (
        422,
        "invalid_response_template",
        "price_amount",
    )
    first_id, second_id = first.json()["id"], second.json()["id"]
    assert await world.templates(performer) == [first_id, second_id]
    assert await world.templates(stranger) == []

    headers = world.headers(performer)
    url = f"{API}/me/response-templates"
    primary = await world.app.client.patch(
        f"{url}/{second_id}", json={"primary": True}, headers=headers
    )
    assert (primary.status_code, primary.json()["primary"]) == (200, True)
    assert await world.templates(performer) == [second_id, first_id]
    edited = await world.app.client.patch(
        f"{url}/{first_id}",
        json={
            "title": "Вечером",
            "message": "Могу вечером.",
            "price_type": "from",
            "price_amount": 2,
        },
        headers=headers,
    )
    assert edited.status_code == 200, edited.text
    assert (edited.json()["title"], edited.json()["message"], edited.json()["primary"]) == (
        "Вечером",
        "Могу вечером.",
        False,
    )
    assert edited.json()["price"] == {"type": "from", "amount": {"amount": 2, "currency": "RSD"}}
    halves = await world.app.client.patch(
        f"{url}/{first_id}", json={"price_amount": 5}, headers=headers
    )
    assert halves.status_code == 422  # предложение меняется только целиком
    foreign = world.headers(stranger)
    stolen = await world.app.client.patch(
        f"{url}/{first_id}", json={"primary": True}, headers=foreign
    )
    removed_by_stranger = await world.app.client.delete(f"{url}/{first_id}", headers=foreign)
    assert (stolen.status_code, stolen.json()["code"]) == (404, "response_template_not_found")
    assert removed_by_stranger.status_code == 404

    removed = await world.app.client.delete(f"{url}/{second_id}", headers=headers)
    assert removed.status_code == 204
    assert await world.templates(performer) == [first_id]  # основным стал оставшийся
    again = await world.app.client.delete(f"{url}/{second_id}", headers=headers)
    assert (again.status_code, again.json()["code"]) == (404, "response_template_not_found")
    replacement = await world.template(performer, "Снова второй")
    assert replacement.status_code == 201, replacement.text
    assert await world.templates(performer) == [first_id, replacement.json()["id"]]


async def test_parallel_new_templates_stop_at_two(world: World) -> None:
    performer = await world.user()

    replies = await asyncio.gather(*(world.template(performer, f"Шаблон {n}") for n in range(4)))

    assert sorted(reply.status_code for reply in replies) == [201, 201, 409, 409]
    positions = await world.scalar(
        "SELECT array_agg(position ORDER BY position) FROM jobs.response_templates"
        " WHERE user_id = :user AND deleted_at IS NULL",
        user=performer,
    )
    assert positions == [0, 1]


async def test_response_from_a_template_and_the_performer_sees_it_on_the_job(
    world: World,
) -> None:
    client, performer, other = await world.user(), await world.user(), await world.user()
    job_id = await world.job(client)
    template = (await world.template(performer, "Могу сегодня")).json()
    foreign = (await world.template(other, "Чужой")).json()

    stolen = await world.respond(performer, job_id, template_id=foreign["id"])
    assert (stolen.status_code, stolen.json()["code"]) == (404, "response_template_not_found")
    response = await world.responded(performer, job_id, template_id=template["id"])

    stored = await world.scalar(
        "SELECT template_id FROM jobs.responses WHERE id = :id", id=UUID(response["id"])
    )
    assert stored == UUID(template["id"])
    url = f"{API}/jobs/{job_id}"
    mine = (await world.app.client.get(url, headers=world.headers(performer))).json()
    assert mine["my_response"] == {"id": response["id"], "status": "submitted", "review": "pending"}
    for headers in (world.headers(client), world.headers(other), {}):
        assert (await world.app.client.get(url, headers=headers)).json()["my_response"] is None


async def test_deleted_account_templates_are_forgotten(
    world: World, worker: AsyncContainer
) -> None:
    performer = await world.user()
    stranger = await world.user()
    foreign = await world.template(stranger, "Чужой шаблон", availability_note="После работы")
    active = await world.template(performer, "Могу сегодня", availability_note="После работы")
    deleted = await world.template(performer, "Старый шаблон", availability_note="По вечерам")
    for reply in (foreign, active, deleted):
        assert reply.status_code == 201, reply.text
    deleted_id = UUID(deleted.json()["id"])
    removed = await world.app.client.delete(
        f"{API}/me/response-templates/{deleted_id}", headers=world.headers(performer)
    )
    assert removed.status_code == 204
    deleted_at = await world.scalar(
        "SELECT deleted_at FROM jobs.response_templates WHERE id = :id", id=deleted_id
    )
    assert deleted_at is not None

    for _ in range(2):  # повторная доставка UserDeleted тоже не оставляет личных текстов
        async with worker() as request:
            await (await request.get(ForgetClientJobs))(ForgetClientJobsCommand(user_id=performer))

        kept = await world.scalar(
            "SELECT count(*) FROM jobs.response_templates WHERE user_id = :user"
            " AND (deleted_at IS NULL OR message <> '—' OR title <> '—'"
            " OR availability_note IS NOT NULL)",
            user=performer,
        )
        assert kept == 0
        assert await world.templates(performer) == []
        assert (
            await world.scalar(
                "SELECT deleted_at FROM jobs.response_templates WHERE id = :id", id=deleted_id
            )
            == deleted_at
        )

    untouched = await world.scalar(
        "SELECT count(*) FROM jobs.response_templates WHERE id = :id"
        " AND deleted_at IS NULL AND title = :title AND message = :message"
        " AND availability_note = :note",
        id=UUID(foreign.json()["id"]),
        title=foreign.json()["title"],
        message=foreign.json()["message"],
        note=foreign.json()["availability_note"],
    )
    assert untouched == 1
