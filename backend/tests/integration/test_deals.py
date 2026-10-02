"""Выбор исполнителя и сделка (DEVELOPMENT_PLAN 6.1a) через API: «Выбрать исполнителем» создаёт
сделку `agreed` в той же транзакции (сбой сделки откатывает выбор), остальные отклики — «не
выбран», заявка «в работе», адрес видит только выбранный исполнитель. «Работа выполнена» от
обеих сторон завершает сделку и заявку; отмена с причиной снова открывает заявку, прежние
кандидаты ждут решения. «В избранные», «отклонить», подтверждение «Договорились» и списки
сделок. Третья завершённая сделка поднимает обеим сторонам уровень доверия до 2; удалённый
аккаунт отменяет свои сделки. Данные коммитятся.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_worker_container, module_routers
from app.modules.deals.application.use_cases.cancel_user_deals import (
    CancelUserDeals,
    CancelUserDealsCommand,
)
from app.modules.identity.application.use_cases.record_completed_deal import (
    RecordCompletedDeal,
    RecordCompletedDealCommand,
)
from app.modules.jobs.application.use_cases.accept_response import (
    AcceptResponse,
    AcceptResponseCommand,
)
from app.modules.jobs.domain.response import ResponseId
from app.platform.kernel.ids import DealId, UserId, new_id
from app.platform.settings import Settings
from tests.plugins.http import HttpApp, bearer, http_app
from tests.plugins.identity import accept_rules, insert_user
from tests.plugins.queue import run_queued

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


@pytest.fixture
async def worker(storage_settings: Settings) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(storage_settings)
    try:
        yield container
    finally:
        await container.close()


class World:
    def __init__(self, app: HttpApp, settings: Settings) -> None:
        self.app, self.settings = app, settings
        self.users: list[UserId] = []

    async def scalar(self, sql: str, **params: object) -> Any:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar()

    async def execute(self, sql: str, **params: object) -> None:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)

    async def user(self) -> UserId:
        async with self.app.container() as request:
            session = await request.get(AsyncSession)
            user_id = await insert_user(session)
            await accept_rules(session, user_id)
        self.users.append(user_id)
        return user_id

    async def job(self, client_id: UserId) -> UUID:
        """Опубликованная заявка с адресом — строкой: модерация заявки тесту не нужна."""
        job_id = new_id()
        category = await self.scalar(
            "SELECT min(id) FROM catalog.categories WHERE is_active AND jobs_enabled"
            " AND risk_level = 0 AND parent_id IS NOT NULL"
        )
        path = await self.scalar("SELECT path FROM catalog.categories WHERE id = :id", id=category)
        now = datetime.now(UTC)
        await self.execute(
            "INSERT INTO jobs.jobs (id, client_id, status, title, description, content_lang,"
            " category_id, category_path, urgency, budget_type, budget_min, city_id,"
            " address_private, point_exact, published_at, expires_at, version)"
            " VALUES (:id, :client, 'published', 'Повесить люстру', 'Люстра на пять рожков',"
            " 'ru', :category, :path, 'this_week', 'fixed', 500000,"
            " (SELECT id FROM geo.cities WHERE slug = 'novi-sad'), :address,"
            " ST_GeogFromText('SRID=4326;POINT(19.84 45.25)'), :published, :expires, 1)",
            id=job_id,
            client=client_id,
            category=category,
            path=list(path),
            address=ADDRESS,
            published=now - timedelta(minutes=30),
            expires=now + timedelta(days=7),
        )
        return job_id

    def headers(self, user_id: UserId) -> dict[str, str]:
        return bearer(self.settings, user_id)

    async def response(self, performer: UserId, job_id: UUID) -> str:
        """Отклик, уже прошедший проверку: клиент его видит."""
        body = {
            "message": f"Здравствуйте! Могу сегодня в 19:00. {new_id().hex[-8:]}",
            "price_type": "fixed",
            "price_amount": 350_000,
            "availability_note": "Сегодня, 19:00",
        }
        headers = self.headers(performer) | {"Idempotency-Key": new_id().hex}
        reply = await self.app.client.post(
            f"{API}/jobs/{job_id}/responses", json=body, headers=headers
        )
        assert reply.status_code == 201, reply.text
        response_id: str = reply.json()["id"]
        await self.execute(
            "UPDATE jobs.responses SET review = 'clear' WHERE id = :id", id=UUID(response_id)
        )
        return response_id

    async def post(self, user: UserId, path: str, body: Any = None) -> httpx.Response:
        return await self.app.client.post(f"{API}{path}", json=body, headers=self.headers(user))

    async def get(self, user: UserId, path: str) -> httpx.Response:
        return await self.app.client.get(f"{API}{path}", headers=self.headers(user))

    async def accepted(self, client: UserId, response_id: str) -> str:
        reply = await self.post(client, f"/responses/{response_id}/accept")
        assert reply.status_code == 200, reply.text
        deal_id: str = reply.json()["deal_id"]
        return deal_id

    async def job_row(self, job_id: UUID) -> Any:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return (
                await conn.execute(
                    text(
                        "SELECT status, responses_count, selected_response_id, close_reason"
                        " FROM jobs.jobs WHERE id = :id"
                    ),
                    {"id": job_id},
                )
            ).one()

    async def statuses(self, job_id: UUID) -> dict[str, str]:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("SELECT id, status FROM jobs.responses WHERE job_id = :id"),
                    {"id": job_id},
                )
            ).all()
        return {str(row.id): row.status for row in rows}


@pytest.fixture
async def world(web: HttpApp, storage_settings: Settings) -> AsyncIterator[World]:
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


async def test_accept_creates_an_agreed_deal_and_assigns_the_job(world: World) -> None:
    client, chosen, other, stranger = (
        await world.user(),
        await world.user(),
        await world.user(),
        await world.user(),
    )
    job_id = await world.job(client)
    chosen_response = await world.response(chosen, job_id)
    other_response = await world.response(other, job_id)

    reply = await world.post(client, f"/responses/{chosen_response}/accept")

    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert (body["job"]["status"], body["job"]["responses_count"]) == ("assigned", 0)
    deal_id = body["deal_id"]
    deal = (await world.get(client, f"/deals/{deal_id}")).json()
    assert {key: deal[key] for key in ("status", "origin", "my_role", "title", "job_id")} == {
        "status": "agreed",
        "origin": "job_response",
        "my_role": "client",
        "title": "Повесить люстру",
        "job_id": str(job_id),
    }
    assert deal["price"] == {"type": "fixed", "amount": {"amount": 350_000, "currency": "RSD"}}
    assert deal["performer_id"] == str(chosen)
    performer_view = (await world.get(chosen, f"/deals/{deal_id}")).json()
    assert performer_view["my_role"] == "performer"
    assert (await world.get(stranger, f"/deals/{deal_id}")).status_code == 404
    assert await world.statuses(job_id) == {
        chosen_response: "accepted",
        other_response: "not_selected",
    }
    # адрес — только выбранному: заявка «в работе» другим больше не видна
    job_for_chosen = await world.get(chosen, f"/jobs/{job_id}")
    assert job_for_chosen.status_code == 200, job_for_chosen.text
    assert job_for_chosen.json()["address_private"] == ADDRESS
    assert job_for_chosen.json()["point_exact"] is not None
    assert (await world.get(other, f"/jobs/{job_id}")).status_code == 404
    again = await world.post(client, f"/responses/{other_response}/accept")
    assert (again.status_code, again.json()["code"]) == (409, "job_not_open")
    history = await world.scalar(
        "SELECT count(*) FROM deals.status_history WHERE deal_id = :id AND from_status IS NULL"
        " AND to_status = 'agreed'",
        id=UUID(deal_id),
    )
    assert history == 1


async def test_deal_failure_rolls_back_the_accept(world: World) -> None:
    """Сделку не создать (отклик уже занят другой сделкой) — выбор отклика тоже откатывается."""
    client, performer = await world.user(), await world.user()
    job_id = await world.job(client)
    response_id = await world.response(performer, job_id)
    await world.execute(
        "INSERT INTO deals.deals (id, client_id, performer_id, origin, job_id, response_id,"
        " title_snapshot, status, version) VALUES (:id, :client, :performer, 'job_response',"
        " :job, :response, 'Повесить люстру', 'cancelled', 1)",
        id=new_id(),
        client=client,
        performer=performer,
        job=job_id,
        response=UUID(response_id),
    )

    async with world.app.container() as request:
        accept = await request.get(AcceptResponse)
        with pytest.raises(IntegrityError):
            await accept(
                AcceptResponseCommand(actor_id=client, response_id=ResponseId(UUID(response_id)))
            )

    row = await world.job_row(job_id)
    assert (row.status, row.responses_count, row.selected_response_id) == ("published", 1, None)
    assert await world.statuses(job_id) == {response_id: "submitted"}


async def test_both_marks_complete_the_deal_and_the_job(
    world: World, worker: AsyncContainer
) -> None:
    client, performer = await world.user(), await world.user()
    job_id = await world.job(client)
    response_id = await world.response(performer, job_id)
    deal_id = await world.accepted(client, response_id)

    first = await world.post(client, f"/deals/{deal_id}/complete")
    again = await world.post(client, f"/deals/{deal_id}/complete")
    second = await world.post(performer, f"/deals/{deal_id}/complete")

    assert first.status_code == 200, first.text
    assert (first.json()["status"], first.json()["i_marked_done"]) == ("agreed", True)
    assert again.json()["status"] == "agreed"
    performer_view = second.json()
    assert (performer_view["status"], performer_view["other_marked_done"]) == ("completed", True)
    assert await run_queued(worker, "jobs.complete_job", user_id=client, by="client_id") == 1
    row = await world.job_row(job_id)
    assert (row.status, row.close_reason) == ("completed", "hired_here")
    # завершённую заявку выбранный исполнитель по-прежнему видит с адресом
    job_for_performer = await world.get(performer, f"/jobs/{job_id}")
    assert job_for_performer.json()["address_private"] == ADDRESS
    cancel = await world.post(client, f"/deals/{deal_id}/cancel", {"reason": "other"})
    assert (cancel.status_code, cancel.json()["code"]) == (409, "deal_not_active")


async def test_cancelled_deal_reopens_the_job(world: World, worker: AsyncContainer) -> None:
    client, chosen, other = await world.user(), await world.user(), await world.user()
    job_id = await world.job(client)
    chosen_response = await world.response(chosen, job_id)
    other_response = await world.response(other, job_id)
    deal_id = await world.accepted(client, chosen_response)

    reply = await world.post(chosen, f"/deals/{deal_id}/cancel", {"reason": "plans_changed"})

    assert reply.status_code == 200, reply.text
    assert {key: reply.json()[key] for key in ("status", "cancelled_by_me", "cancel_reason")} == {
        "status": "cancelled",
        "cancelled_by_me": True,
        "cancel_reason": "plans_changed",
    }
    assert await run_queued(worker, "jobs.reopen_job", user_id=client, by="client_id") == 1
    row = await world.job_row(job_id)
    assert (row.status, row.responses_count, row.selected_response_id) == ("published", 1, None)
    assert await world.statuses(job_id) == {
        chosen_response: "withdrawn",  # отменил исполнитель
        other_response: "viewed",  # прежний кандидат снова ждёт решения
    }
    # выбрать можно из восстановленных
    assert (await world.post(client, f"/responses/{other_response}/accept")).status_code == 200


async def test_cancel_reason_is_chosen_by_a_party(world: World) -> None:
    client, performer = await world.user(), await world.user()
    job_id = await world.job(client)
    deal_id = await world.accepted(client, await world.response(performer, job_id))

    system_reason = await world.post(client, f"/deals/{deal_id}/cancel", {"reason": "expired"})
    unknown = await world.post(client, f"/deals/{deal_id}/cancel", {"reason": "bored"})
    stranger = await world.post(await world.user(), f"/deals/{deal_id}/cancel", {"reason": "other"})

    assert (system_reason.status_code, system_reason.json()["code"]) == (422, "invalid_deal")
    assert unknown.status_code == 422
    assert stranger.status_code == 404


async def test_shortlist_and_decline(world: World) -> None:
    client, first, second = await world.user(), await world.user(), await world.user()
    job_id = await world.job(client)
    liked = await world.response(first, job_id)
    declined = await world.response(second, job_id)

    shortlisted = await world.post(client, f"/responses/{liked}/shortlist")
    rejected = await world.post(client, f"/responses/{declined}/decline")
    foreign = await world.post(first, f"/responses/{liked}/decline")

    assert shortlisted.status_code == 200, shortlisted.text
    assert rejected.json()["responses_count"] == 1
    assert await world.statuses(job_id) == {liked: "shortlisted", declined: "declined"}
    assert foreign.status_code == 404  # решает только клиент


async def test_proposal_is_confirmed_by_the_other_party(world: World) -> None:
    """«Договорились» из чата (6.4): предложение подтверждает вторая сторона."""
    client, performer = await world.user(), await world.user()
    deal_id = new_id()
    await world.execute(
        "INSERT INTO deals.deals (id, client_id, performer_id, origin, title_snapshot, status,"
        " proposed_by, version) VALUES (:id, :client, :performer, 'chat', 'Уборка квартиры',"
        " 'proposed', :performer, 1)",
        id=deal_id,
        client=client,
        performer=performer,
    )

    own = await world.post(performer, f"/deals/{deal_id}/confirm")
    awaiting = (await world.get(client, f"/deals/{deal_id}")).json()
    confirmed = await world.post(client, f"/deals/{deal_id}/confirm")

    assert (own.status_code, own.json()["code"]) == (409, "deal_not_active")
    assert awaiting["awaits_my_confirmation"] is True
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "agreed"


async def test_my_deals_by_role_and_status(world: World) -> None:
    client, performer = await world.user(), await world.user()
    first = await world.accepted(client, await world.response(performer, await world.job(client)))
    second = await world.accepted(client, await world.response(performer, await world.job(client)))
    await world.post(client, f"/deals/{first}/cancel", {"reason": "no_contact"})

    async def ids(user: UserId, query: str) -> list[str]:
        reply = await world.get(user, f"/me/deals{query}")
        assert reply.status_code == 200, reply.text
        return [item["id"] for item in reply.json()["items"]]

    assert await ids(client, "") == [second, first]  # новые первыми
    assert await ids(client, "?role=client&status=agreed") == [second]
    assert await ids(client, "?role=performer") == []
    assert await ids(performer, "?role=performer&status=cancelled") == [first]
    page = (await world.get(client, "/me/deals?limit=1")).json()
    assert [item["id"] for item in page["items"]] == [second]
    rest = (await world.get(client, f"/me/deals?limit=1&cursor={page['next_cursor']}")).json()
    assert ([item["id"] for item in rest["items"]], rest["next_cursor"]) == ([first], None)


async def test_third_completed_deal_verifies_both_sides(
    world: World, worker: AsyncContainer
) -> None:
    client, performer = await world.user(), await world.user()
    deals = []
    for _ in range(3):
        deal_id = await world.accepted(
            client, await world.response(performer, await world.job(client))
        )
        for side in (client, performer):
            assert (await world.post(side, f"/deals/{deal_id}/complete")).status_code == 200
        deals.append(deal_id)

    recorded = await run_queued(
        worker, "identity.record_completed_deal", user_id=client, by="client_id"
    )

    assert recorded == 3
    levels = [
        await world.scalar("SELECT trust_level FROM identity.users WHERE id = :id", id=user)
        for user in (client, performer)
    ]
    assert levels == [2, 2]  # «Новые» аккаунты: уровень даёт только число сделок
    async with worker() as request:  # повтор задачи — тот же факт, ничего нового
        again = await (await request.get(RecordCompletedDeal))(
            RecordCompletedDealCommand(
                deal_id=DealId(UUID(deals[0])),
                user_ids=(client, performer),
                completed_at=datetime.now(UTC),
            )
        )
    assert again == 0
    facts = await world.scalar(
        "SELECT count(*) FROM identity.completed_deals WHERE user_id IN (:client, :performer)",
        client=client,
        performer=performer,
    )
    assert facts == 6


async def test_deleted_account_cancels_its_deals(world: World, worker: AsyncContainer) -> None:
    client, performer = await world.user(), await world.user()
    job_id = await world.job(client)
    response_id = await world.response(performer, job_id)
    deal_id = await world.accepted(client, response_id)

    async with worker() as request:
        cancelled = await (await request.get(CancelUserDeals))(
            CancelUserDealsCommand(user_id=performer)
        )

    assert cancelled == 1
    engine = await world.app.container.get(AsyncEngine)
    async with engine.connect() as conn:
        deal = (
            await conn.execute(
                text("SELECT status, cancel_reason, cancelled_by FROM deals.deals WHERE id = :id"),
                {"id": UUID(deal_id)},
            )
        ).one()
    assert (deal.status, deal.cancel_reason, deal.cancelled_by) == (
        "cancelled",
        "account_deleted",
        None,
    )
    assert await run_queued(worker, "jobs.reopen_job", user_id=client, by="client_id") == 1
    assert (await world.job_row(job_id)).status == "published"
    assert await world.statuses(job_id) == {response_id: "declined"}
