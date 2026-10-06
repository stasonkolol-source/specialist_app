"""Уведомления о сделках (DEVELOPMENT_PLAN 6.1b; ARCHITECTURE §11.3): выбранному — «Вас
выбрали» со ссылкой на сделку, остальным откликнувшимся — «Выбрали другого» со ссылкой на «Мои
отклики», второй стороне — отмена с причиной (клиенту — «заявка снова открыта»), «Работа
выполнена?» — тем, кто ещё не отметил; исходы исполнителю в центре S42 — «Клиент отклонил»,
«Сделка выполнена» (UX-аудит №11). Подписчики выполняются из очереди. Данные коммитятся.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_worker_container, module_routers
from app.modules.deals.application.ports import DealSweep
from app.modules.deals.application.use_cases.sweep_deals import SweepDeals, SweepDealsCommand
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from app.platform.telegram.deeplinks import LinkType, StartLink, encode_start_param
from tests.plugins.http import HttpApp, bearer, http_app
from tests.plugins.identity import accept_rules, insert_user
from tests.plugins.queue import run_queued

pytestmark = pytest.mark.integration

API = "/api/v1"
RESPONSES_LINK = "m_responses"
"""«Мои отклики» S17: чужую заявку после исхода исполнителю не открыть."""


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

    async def execute(self, sql: str, **params: object) -> Any:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.begin() as conn:
            result = await conn.execute(text(sql), params)
            return result.all() if result.returns_rows else None

    async def user(self) -> UserId:
        async with self.app.container() as request:
            session = await request.get(AsyncSession)
            user_id = await insert_user(session)
            await accept_rules(session, user_id)
        return user_id

    async def job(self, client_id: UserId) -> UUID:
        job_id = new_id()
        now = datetime.now(UTC)
        await self.execute(
            "INSERT INTO jobs.jobs (id, client_id, status, title, description, content_lang,"
            " category_id, category_path, urgency, budget_type, city_id, published_at,"
            " expires_at, version) SELECT :id, :client, 'published', 'Повесить люстру', '', 'ru',"
            " c.id, ARRAY[c.id], 'this_week', 'negotiable', ci.id, :published, :expires, 1"
            " FROM geo.cities ci, (SELECT min(id) AS id FROM catalog.categories"
            " WHERE parent_id IS NOT NULL AND is_active AND jobs_enabled AND risk_level = 0) c"
            " WHERE ci.slug = 'novi-sad'",
            id=job_id,
            client=client_id,
            published=now - timedelta(minutes=30),
            expires=now + timedelta(days=7),
        )
        return job_id

    async def response(self, performer: UserId, job_id: UUID) -> str:
        body = {
            "message": f"Здравствуйте! Могу сегодня. {new_id().hex[-8:]}",
            "price_type": "negotiable",
        }
        headers = bearer(self.settings, performer) | {"Idempotency-Key": new_id().hex}
        reply = await self.app.client.post(
            f"{API}/jobs/{job_id}/responses", json=body, headers=headers
        )
        assert reply.status_code == 201, reply.text
        response_id: str = reply.json()["id"]
        await self.execute(
            "UPDATE jobs.responses SET review = 'clear' WHERE id = :id", id=UUID(response_id)
        )
        return response_id

    async def post(self, user: UserId, path: str, body: Any = None) -> Any:
        reply = await self.app.client.post(
            f"{API}{path}", json=body, headers=bearer(self.settings, user)
        )
        assert reply.status_code == 200, reply.text
        return reply.json()

    async def notifications(self, user: UserId) -> list[tuple[str, dict[str, Any]]]:
        rows = await self.execute(
            "SELECT type, payload FROM notifications.notifications WHERE user_id = :user"
            " ORDER BY id",
            user=user,
        )
        return [(row.type, row.payload) for row in rows]


@pytest.fixture
def world(web: HttpApp, storage_settings: Settings) -> World:
    return World(web, storage_settings)


async def test_chosen_and_passed_over_performers_hear_about_it(
    world: World, worker: AsyncContainer
) -> None:
    client, chosen, other = await world.user(), await world.user(), await world.user()
    job_id = await world.job(client)
    chosen_response = await world.response(chosen, job_id)
    await world.response(other, job_id)

    accepted = await world.post(client, f"/responses/{chosen_response}/accept")
    for task in ("notifications.notify_response_accepted", "notifications.notify_passed_over"):
        assert await run_queued(worker, task, user_id=client, by="client_id") == 1

    link = encode_start_param(StartLink(type=LinkType.DEAL, id=UUID(accepted["deal_id"])))
    assert await world.notifications(chosen) == [
        (
            "response.accepted",
            {"params": {"title": "Повесить люстру"}, "link": link, "urgent": False},
        )
    ]
    assert await world.notifications(other) == [
        (
            "response.not_selected",
            {"params": {"title": "Повесить люстру"}, "link": RESPONSES_LINK, "urgent": False},
        )
    ]
    assert await world.notifications(client) == []


@pytest.mark.parametrize("how", ["close", "delete"])
async def test_closed_job_tells_waiting_performers_it_was_closed(
    world: World, worker: AsyncContainer, how: str
) -> None:
    """MU-11: клиент закрыл («Уже не нужно») или удалил заявку — откликнувшимся «Заявку закрыли»,
    отозвавшему отклик раньше — ничего."""
    client, waiting, gone = await world.user(), await world.user(), await world.user()
    job_id = await world.job(client)
    await world.response(waiting, job_id)
    await world.post(gone, f"/responses/{await world.response(gone, job_id)}/withdraw")

    if how == "close":
        await world.post(client, f"/jobs/{job_id}/close", {"reason": "not_needed"})
    else:
        deleted = await world.app.client.delete(
            f"{API}/jobs/{job_id}", headers=bearer(world.settings, client)
        )
        assert deleted.status_code == 204, deleted.text
    task = "notifications.notify_job_closed"
    assert await run_queued(worker, task, user_id=client, by="client_id") == 1

    assert await world.notifications(waiting) == [
        (
            "response.not_selected",
            {
                "params": {"title": "Повесить люстру", "reason": "job_closed"},
                "link": RESPONSES_LINK,
                "urgent": False,
            },
        )
    ]
    assert await world.notifications(gone) == []
    assert await world.notifications(client) == []


async def test_declined_performer_finds_the_outcome_in_the_center(
    world: World, worker: AsyncContainer
) -> None:
    """№11: клиент отклонил отклик — у исполнителя строка в S42 «Клиент отклонил отклик»,
    нажимается («Мои отклики»); в бот не уходит — исход, а не повод действовать."""
    client, performer = await world.user(), await world.user()
    job_id = await world.job(client)
    response_id = await world.response(performer, job_id)

    await world.post(client, f"/responses/{response_id}/decline")
    task = "notifications.notify_response_declined"
    assert await run_queued(worker, task, user_id=client, by="client_id") == 1

    assert await world.notifications(performer) == [
        (
            "response.declined",
            {"params": {"title": "Повесить люстру"}, "link": RESPONSES_LINK, "urgent": False},
        )
    ]
    [(in_app, deliveries)] = await world.execute(
        "SELECT n.in_app, count(d.id) FROM notifications.notifications n"
        " LEFT JOIN notifications.deliveries d ON d.notification_id = n.id"
        " WHERE n.user_id = :user GROUP BY n.id",
        user=performer,
    )
    assert (in_app, deliveries) == (True, 0)


@pytest.mark.parametrize("last", ["client", "performer"])
async def test_completed_deal_reaches_the_performer_when_the_client_confirms(
    world: World, worker: AsyncContainer, last: str
) -> None:
    """№11: клиент подтвердил работу последним — исполнителю в S42 «Сделка выполнена» со ссылкой
    на сделку; последним отметил сам исполнитель — строки нет: итог он видел на экране."""
    client, performer = await world.user(), await world.user()
    job_id = await world.job(client)
    accepted = await world.post(
        client, f"/responses/{await world.response(performer, job_id)}/accept"
    )
    deal_id = UUID(accepted["deal_id"])
    first, second = (performer, client) if last == "client" else (client, performer)

    await world.post(first, f"/deals/{deal_id}/complete")
    await world.post(second, f"/deals/{deal_id}/complete")
    task = "notifications.notify_deal_completed"
    assert await run_queued(worker, task, user_id=client, by="client_id") == 1

    completed = [n for n in await world.notifications(performer) if n[0] == "deal.completed"]
    link = encode_start_param(StartLink(type=LinkType.DEAL, id=deal_id))
    payload = {
        "params": {"title": "Повесить люстру", "by": "client"},
        "link": link,
        "urgent": False,
    }
    assert completed == ([("deal.completed", payload)] if last == "client" else [])


async def test_cancellation_reaches_the_other_party(world: World, worker: AsyncContainer) -> None:
    client, performer = await world.user(), await world.user()
    job_id = await world.job(client)
    accepted = await world.post(
        client, f"/responses/{await world.response(performer, job_id)}/accept"
    )

    await world.post(performer, f"/deals/{accepted['deal_id']}/cancel", {"reason": "no_contact"})
    assert (
        await run_queued(
            worker, "notifications.notify_deal_cancelled", user_id=client, by="client_id"
        )
        == 1
    )

    [(_, payload)] = [n for n in await world.notifications(client) if n[0] == "deal.cancelled"]
    assert payload["params"] == {
        "title": "Повесить люстру",
        "by": "performer",
        "reason": "no_contact",
        "reopened": "true",
    }
    assert [kind for kind, _ in await world.notifications(performer)] == []  # отменил сам


async def test_completion_prompt_asks_who_has_not_marked(
    world: World, worker: AsyncContainer
) -> None:
    client, performer = await world.user(), await world.user()
    job_id = await world.job(client)
    accepted = await world.post(
        client, f"/responses/{await world.response(performer, job_id)}/accept"
    )
    deal_id = UUID(accepted["deal_id"])
    await world.post(performer, f"/deals/{deal_id}/complete")
    await world.execute(
        "UPDATE deals.deals SET agreed_at = now() - interval '25 hours' WHERE id = :id", id=deal_id
    )

    async with worker() as request:
        await (await request.get(SweepDeals))(SweepDealsCommand(sweep=DealSweep.PROMPT))
    assert (
        await run_queued(
            worker, "notifications.notify_deal_completion", user_id=client, by="client_id"
        )
        == 1
    )

    prompts = [n for n in await world.notifications(client) if n[0] == "deal.completion_prompt"]
    assert [payload["params"]["deal_id"] for _, payload in prompts] == [str(deal_id)]
    assert [
        n for n in await world.notifications(performer) if n[0] == "deal.completion_prompt"
    ] == []  # исполнитель уже отметил
