"""Срок заявки (DEVELOPMENT_PLAN 5.1; ARCHITECTURE §7.9, §11.3, §12): за два часа до конца —
напоминание «Продлить / Закрыть», после — «истекла» и уведомление. Периодические задачи
выполняются как в воркере; подписчики — так, как их выполнил бы воркер. Данные коммитятся.
"""

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_worker_container
from app.modules.jobs.api import JobsApi
from app.modules.jobs.application.content import JobDraft
from app.modules.jobs.application.use_cases.create_job import CreateJob, CreateJobCommand
from app.modules.jobs.application.use_cases.expire_jobs import ExpireJobs, ExpireJobsCommand
from app.modules.jobs.application.use_cases.extend_job import ExtendJob, ExtendJobCommand
from app.modules.jobs.application.use_cases.remind_expiring_jobs import (
    RemindExpiringJobs,
    RemindExpiringJobsCommand,
)
from app.modules.jobs.domain.job import Budget, BudgetType, JobId, Urgency
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CategoryId, CityId, UserId, new_id
from app.platform.settings import Settings
from app.platform.telegram.deeplinks import LinkType, StartLink, encode_start_param
from tests.plugins.identity import accept_rules, insert_user
from tests.plugins.queue import run_queued

pytestmark = pytest.mark.integration


class World:
    """Контейнер воркера и пользователи теста: их задачи в очереди убираются после теста."""

    def __init__(self, container: AsyncContainer) -> None:
        self.container = container
        self.ids: list[UUID] = []

    async def scalar(self, sql: str, **params: object) -> Any:
        engine = await self.container.get(AsyncEngine)
        async with engine.connect() as conn:
            return (await conn.execute(text(sql), params)).scalar()

    async def execute(self, sql: str, **params: object) -> None:
        engine = await self.container.get(AsyncEngine)
        async with engine.begin() as conn:
            await conn.execute(text(sql), params)

    async def client(self) -> UserId:
        """Клиент с ботом без тихих часов: доставка в Telegram создаётся в любое время суток."""
        async with self.container() as request:
            session = await request.get(AsyncSession)
            user_id = await insert_user(session)
            await accept_rules(session, user_id)
        await self.execute(
            "INSERT INTO notifications.channels (id, user_id, kind, address, granted_via,"
            " granted_at) VALUES (:id, :user, 'telegram', :address, 'bot_start', now())",
            id=new_id(),
            user=user_id,
            address=str(700_000_000 + new_id().int % 100_000_000),
        )
        await self.execute(
            "INSERT INTO notifications.user_settings (user_id, quiet_enabled)"
            " VALUES (:user, false)",
            user=user_id,
        )
        self.ids.append(user_id)
        return user_id

    async def published(self, client_id: UserId) -> JobId:
        category = await self.scalar(
            "SELECT min(id) FROM catalog.categories WHERE is_active AND jobs_enabled"
            " AND risk_level = 0 AND parent_id IS NOT NULL"
        )
        city = await self.scalar("SELECT id FROM geo.cities WHERE slug = 'novi-sad'")
        draft = JobDraft(
            title="Повесить люстру в спальне",
            description="Люстра на пять рожков, потолок 2,7 м.",
            category_id=CategoryId(category),
            urgency=Urgency.THIS_WEEK,
            budget=Budget(type=BudgetType.NEGOTIABLE),
            city_id=CityId(city),
            content_lang="ru",
        )
        async with self.container() as request:
            job_id = await (await request.get(CreateJob))(
                CreateJobCommand(actor_id=client_id, trust_level=0, draft=draft)
            )
            async with await request.get(UnitOfWork):
                await (await request.get(JobsApi)).approve_job(job_id, version=None)
        self.ids.append(job_id)
        return job_id

    async def expires_in(self, job_id: JobId, interval: str) -> None:
        """Сдвинуть срок заявки: `interval` — смещение от now() в SQL («-1 minute»)."""
        await self.execute(
            "UPDATE jobs.jobs SET expires_at = now() + CAST(:interval AS interval) WHERE id = :id",
            interval=interval,
            id=job_id,
        )

    async def notifications(self, user_id: UserId) -> list[dict[str, Any]]:
        engine = await self.container.get(AsyncEngine)
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT n.type, n.payload, n.in_app, d.status AS delivery"
                    " FROM notifications.notifications n"
                    " LEFT JOIN notifications.deliveries d ON d.notification_id = n.id"
                    " WHERE n.user_id = :user ORDER BY n.id"
                ),
                {"user": user_id},
            )
            return [dict(row._mapping) for row in rows]

    async def queued(self, task: str, job_id: JobId) -> int:
        return int(
            await self.scalar(
                "SELECT count(*) FROM procrastinate_jobs WHERE task_name = :task"
                " AND status = 'todo' AND args->'payload'->>'job_id' = :id",
                task=task,
                id=str(job_id),
            )
        )


@pytest.fixture
async def world(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[World]:
    container = make_worker_container(storage_settings)
    world = World(container)
    try:
        yield world
        for some_id in world.ids:
            await world.execute(
                "DELETE FROM procrastinate_jobs WHERE status = 'todo' AND args::text LIKE :id",
                id=f"%{some_id}%",
            )
    finally:
        await container.close()


async def remind(world: World) -> int:
    async with world.container() as request:
        return await (await request.get(RemindExpiringJobs))(RemindExpiringJobsCommand())


async def expire(world: World) -> int:
    async with world.container() as request:
        return await (await request.get(ExpireJobs))(ExpireJobsCommand())


async def test_two_hours_before_the_end_the_client_is_reminded_once(world: World) -> None:
    client = await world.client()
    job_id = await world.published(client)
    await world.expires_in(job_id, "90 minutes")

    assert await remind(world) >= 1

    assert await world.scalar(
        "SELECT expiry_reminded_at IS NOT NULL FROM jobs.jobs WHERE id = :id", id=job_id
    )
    task = "notifications.notify_job_expiring"
    assert await run_queued(world.container, task, user_id=job_id, by="job_id") == 1
    [notification] = await world.notifications(client)
    assert (notification["type"], notification["in_app"]) == ("job.expiring", False)
    assert notification["payload"]["params"] == {
        "job_id": str(job_id),
        "title": "Повесить люстру в спальне",
        "can_extend": "true",
    }
    assert notification["payload"]["link"] == encode_start_param(
        StartLink(type=LinkType.JOB, id=job_id)
    )
    assert notification["payload"]["valid_until"] is not None
    assert notification["delivery"] == "queued"
    await remind(world)
    assert await world.queued(task, job_id) == 0  # одно напоминание за срок


async def test_job_past_its_term_expires_and_the_client_is_told(world: World) -> None:
    client = await world.client()
    job_id = await world.published(client)
    await world.expires_in(job_id, "-1 minute")

    assert await expire(world) >= 1

    assert await world.scalar("SELECT status FROM jobs.jobs WHERE id = :id", id=job_id) == (
        "expired"
    )
    assert await world.queued("analytics.capture_job_expired", job_id) == 1
    task = "notifications.notify_job_expired"
    assert await run_queued(world.container, task, user_id=job_id, by="job_id") == 1
    [notification] = await world.notifications(client)
    assert (notification["type"], notification["in_app"]) == ("job.expired", True)
    assert notification["payload"]["params"]["can_extend"] == "true"


async def test_job_extended_before_the_notice_is_not_reported_expired(world: World) -> None:
    client = await world.client()
    job_id = await world.published(client)
    await world.expires_in(job_id, "-1 minute")
    await expire(world)

    async with world.container() as request:
        await (await request.get(ExtendJob))(ExtendJobCommand(actor_id=client, job_id=job_id))
    task = "notifications.notify_job_expired"
    assert await run_queued(world.container, task, user_id=job_id, by="job_id") == 1

    assert await world.notifications(client) == []  # уже снова опубликована — сообщать нечего
    assert await world.scalar("SELECT status FROM jobs.jobs WHERE id = :id", id=job_id) == (
        "published"
    )
