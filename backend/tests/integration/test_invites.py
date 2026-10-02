"""Приглашения и прямой запрос (DEVELOPMENT_PLAN 5.6) через API: клиент зовёт специалистов в
опубликованную заявку — не больше десяти, повтор без дублей, скрытый или свой профиль — ошибка;
приглашённому — уведомление `job.invited` с кнопкой шаблона. Прямой запрос — заявка, которую
видит только приглашённый: после публикации ему уведомление, чужому — 404, в ленте её нет,
откликнуться может только он. Открытие заявки не владельцем — просмотр, раз в сутки от человека.
Отклик шаблоном из бота — тот же отклик, что S16. Данные коммитятся.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import httpx
import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_worker_container, module_routers
from app.modules.jobs.api import JobsApi
from app.modules.jobs.application.use_cases.respond_with_template import (
    RespondWithTemplate,
    RespondWithTemplateCommand,
)
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.domain.template import TemplateId
from app.modules.jobs.errors import TemplateNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId, new_id
from app.platform.settings import Settings
from tests.integration.test_responses import API, World
from tests.plugins.http import HttpApp, http_app
from tests.plugins.identity import insert_restriction
from tests.plugins.queue import run_queued

pytestmark = pytest.mark.integration


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


class Invites(World):
    async def specialist(self, name: str = "Ana") -> tuple[UserId, UUID]:
        """Пользователь с опубликованным профилем — строкой: модерация профиля не нужна."""
        user_id = await self.user(name)
        profile_id = new_id()
        await self.execute(
            "INSERT INTO specialists.profiles (id, user_id, kind, status, display_name, city_id,"
            " created_at, published_at, version) SELECT :id, :user, 'pro', 'published', :name,"
            " c.id, now(), now(), 1 FROM geo.cities c WHERE c.slug = 'novi-sad'",
            id=profile_id,
            user=user_id,
            name=name,
        )
        return user_id, profile_id

    async def invite(self, client: UserId, job_id: UUID, *profiles: UUID) -> httpx.Response:
        return await self.app.client.post(
            f"{API}/jobs/{job_id}/invites",
            json={"profile_ids": [str(p) for p in profiles]},
            headers=self.headers(client),
        )

    async def direct(self, client: UserId, profile_id: UUID) -> httpx.Response:
        body = await self.job_body()
        headers = self.headers(client) | {"Idempotency-Key": new_id().hex}
        return await self.app.client.post(
            f"{API}/specialists/{profile_id}/requests", json=body, headers=headers
        )

    async def job_body(self) -> dict[str, Any]:
        category = await self.scalar(
            "SELECT min(id) FROM catalog.categories WHERE is_active AND jobs_enabled"
            " AND risk_level = 0 AND parent_id IS NOT NULL"
        )
        city = await self.scalar("SELECT id FROM geo.cities WHERE slug = 'novi-sad'")
        return {
            "title": "Собрать шкаф в прихожей",
            "description": "Шкаф PAX, два метра, инструмент есть.",
            "category_id": category,
            "urgency": "this_week",
            "budget_type": "negotiable",
            "city_id": city,
        }

    async def notices(self, user_id: UserId) -> list[dict[str, Any]]:
        engine = await self.app.container.get(AsyncEngine)
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT payload FROM notifications.notifications WHERE user_id = :user"
                        " AND type = 'job.invited'"
                    ),
                    {"user": user_id},
                )
            ).all()
        return [row[0] for row in rows]

    async def get(self, job_id: UUID, viewer: UserId | None) -> httpx.Response:
        headers = self.headers(viewer) if viewer is not None else {}
        return await self.app.client.get(f"{API}/jobs/{job_id}", headers=headers)


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


async def test_invited_specialist_gets_a_notice_with_a_template_button(
    world: Invites, worker: AsyncContainer
) -> None:
    client = await world.user("Елена К.")
    job_id = await world.job(client)
    ana, ana_profile = await world.specialist("Ana")
    marko, marko_profile = await world.specialist("Marko")
    template = await world.template(ana, "Могу сегодня")
    assert template.status_code == 201, template.text

    invited = await world.invite(client, job_id, ana_profile, marko_profile, ana_profile)
    again = await world.invite(client, job_id, ana_profile)

    assert invited.status_code == 200, invited.text
    assert [item["profile_id"] for item in invited.json()["items"]] == [
        str(ana_profile),
        str(marko_profile),
    ]
    assert invited.json()["limit"] == 10
    assert len(again.json()["items"]) == 2  # повтор — без дублей
    events = await world.scalar(
        "SELECT count(*) FROM procrastinate_jobs WHERE task_name ="
        " 'notifications.notify_job_invited' AND args->'payload'->>'job_id' = :job",
        job=str(job_id),
    )
    assert events == 2  # повтор не зовёт второй раз
    sent = await run_queued(
        world.app.container, "notifications.notify_job_invited", user_id=job_id, by="job_id"
    )
    assert sent == 2
    [notice] = await world.notices(ana)
    params = notice["params"]
    assert (params["title"], params["client"], params["direct"]) == (
        "Повесить люстру",
        "Елена К.",
        "false",
    )
    assert params["template_0"] == template.json()["id"]
    assert params["template_0_title"] == "Могу сегодня"
    assert notice["link"].startswith("j_")
    [plain] = await world.notices(marko)
    assert "template_0" not in plain["params"]  # шаблонов нет — только «Посмотреть заявку»
    listed = await world.app.client.get(
        f"{API}/jobs/{job_id}/invites", headers=world.headers(client)
    )
    assert [item["profile_id"] for item in listed.json()["items"]] == [
        str(ana_profile),
        str(marko_profile),
    ]


async def test_inviting_refuses_strangers_own_hidden_and_too_many(world: Invites) -> None:
    client = await world.user()
    job_id = await world.job(client)
    closed = await world.job(client, status="closed")
    _, profile = await world.specialist()
    _, own = await world.specialist()
    await world.execute(
        "UPDATE specialists.profiles SET user_id = :client WHERE id = :id", client=client, id=own
    )
    banned, banned_profile = await world.specialist()
    async with world.app.container() as request:
        await insert_restriction(await request.get(AsyncSession), banned, "banned")
    many = [(await world.specialist())[1] for _ in range(10)]

    stranger = await world.invite(await world.user(), job_id, profile)
    mine = await world.invite(client, job_id, own)
    hidden = await world.invite(client, job_id, banned_profile)
    unknown = await world.invite(client, job_id, new_id())
    late = await world.invite(client, closed, profile)
    batch = await world.invite(client, job_id, profile, *many)  # больше десяти за раз — схема
    filled = await world.invite(client, job_id, *many)
    too_many = await world.invite(client, job_id, profile)

    assert (stranger.status_code, stranger.json()["code"]) == (404, "job_not_found")
    assert (mine.status_code, mine.json()["code"]) == (409, "own_profile_invite")
    assert (hidden.status_code, hidden.json()["code"]) == (404, "invitee_not_found")
    assert (unknown.status_code, unknown.json()["code"]) == (404, "invitee_not_found")
    assert (late.status_code, late.json()["code"]) == (409, "job_not_open")
    assert batch.status_code == 422
    assert filled.status_code == 200, filled.text
    assert (too_many.status_code, too_many.json()["code"], too_many.json()["limit"]) == (
        409,
        "job_invites_full",
        10,
    )


async def test_direct_request_is_seen_and_answered_only_by_the_specialist(
    world: Invites, worker: AsyncContainer
) -> None:
    client = await world.user("Елена К.")
    ana, ana_profile = await world.specialist("Ana")
    stranger = await world.user()

    created = await world.direct(client, ana_profile)

    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["visibility"], body["status"], body["viewer_role"]) == (
        "direct",
        "pending_moderation",
        "owner",
    )
    job_id = UUID(body["id"])
    # проверка пройдена — опубликована (модерация заявки этим тестам не нужна)
    async with worker() as request:
        uow = await request.get(UnitOfWork)
        jobs = await request.get(JobsApi)
        async with uow:
            await jobs.approve_job(job_id, version=None)
    announced = await run_queued(
        world.app.container, "jobs.announce_direct_request", user_id=job_id, by="job_id"
    )
    assert announced == 1
    assert (
        await run_queued(
            world.app.container, "notifications.notify_job_invited", user_id=job_id, by="job_id"
        )
        == 1
    )
    [notice] = await world.notices(ana)
    assert notice["params"]["direct"] == "true"

    assert (await world.get(job_id, ana)).status_code == 200
    assert (await world.get(job_id, stranger)).json()["code"] == "job_not_found"
    assert (await world.get(job_id, None)).status_code == 404
    feed = await world.app.client.get(
        f"{API}/jobs",
        params={"city_id": body["city_id"]},
        headers=world.headers(stranger),
    )
    assert str(job_id) not in {item["id"] for item in feed.json()["items"]}
    refused = await world.respond(stranger, job_id)
    assert (refused.status_code, refused.json()["code"]) == (404, "job_not_found")
    assert (await world.respond(ana, job_id)).status_code == 201
    own = await world.direct(client, (await world.specialist())[1])
    assert own.status_code == 201
    self_request = await world.direct(ana, ana_profile)
    assert (self_request.status_code, self_request.json()["code"]) == (409, "own_profile_invite")


async def test_views_count_once_a_day_per_person_and_only_for_the_owner(world: Invites) -> None:
    client = await world.user()
    job_id = await world.job(client)
    first, second = await world.user(), await world.user()

    for viewer in (first, first, second, client, None):
        assert (await world.get(job_id, viewer)).status_code == 200

    own = (await world.get(job_id, client)).json()
    assert own["views_count"] == 2  # владелец и гость не считаются, повтор — тоже
    assert (await world.get(job_id, first)).json()["views_count"] is None
    version = await world.scalar("SELECT version FROM jobs.jobs WHERE id = :id", id=job_id)
    assert version == 1  # просмотр не меняет версию заявки (If-Match владельца)


async def test_bot_template_button_responds_like_the_form(
    world: Invites, worker: AsyncContainer
) -> None:
    client = await world.user()
    job_id = await world.job(client)
    performer = await world.user()
    template = (await world.template(performer, "Могу сегодня")).json()

    async with worker() as request:
        respond = await request.get(RespondWithTemplate)
        used, response_id = await respond(
            RespondWithTemplateCommand(
                actor_id=performer,
                trust_level=0,
                job_id=JobId(job_id),
                template_id=TemplateId(UUID(template["id"])),
            )
        )

    assert used.title == "Могу сегодня"
    stored = await world.scalar(
        "SELECT template_id FROM jobs.responses WHERE id = :id", id=response_id
    )
    assert stored == UUID(template["id"])
    deleted = await world.app.client.delete(
        f"{API}/me/response-templates/{template['id']}", headers=world.headers(performer)
    )
    assert deleted.status_code == 204
    other = await world.job(client)
    async with worker() as request:
        respond = await request.get(RespondWithTemplate)
        with pytest.raises(TemplateNotFoundError):
            await respond(
                RespondWithTemplateCommand(
                    actor_id=performer,
                    trust_level=0,
                    job_id=JobId(other),
                    template_id=TemplateId(UUID(template["id"])),
                )
            )
