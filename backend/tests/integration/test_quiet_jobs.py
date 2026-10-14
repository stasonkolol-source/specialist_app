"""Заявка без откликов не висит в тишине (аудит клиента п. 1, роста п. 1, 6): публикация ставит
карточку concierge через 20 минут и клиенту «Поделитесь заявкой» через час; карточка уходит в чат
модераторов, пока на заявку никто не откликнулся (видимые клиенту отклики, отозванные и скрытые не
в счёт), клиенту — одно сообщение на заявку и только пока откликов нет совсем. Подписчики
выполняются так, как их выполнил бы воркер. Данные коммитятся.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_worker_container
from app.modules.catalog.api import CatalogApi
from app.modules.geo.api import GeoApi
from app.modules.jobs.api import JobsApi
from app.modules.jobs.application.content import JobDraft
from app.modules.jobs.application.use_cases.create_job import CreateJob, CreateJobCommand
from app.modules.jobs.domain.job import Budget, BudgetType, JobId, Urgency
from app.modules.moderation.application.use_cases.post_concierge_card import (
    PostConciergeCard,
    PostConciergeCardCommand,
)
from app.modules.moderation.infrastructure.chat import TelegramModeratorsChat
from app.modules.notifications.application.use_cases.notify import Notify
from app.modules.notifications.tasks import notify_no_responses
from app.platform.contracts.events.jobs import JobPublished
from app.platform.db.port import UnitOfWork
from app.platform.i18n.translator import Translator
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import CategoryId, CityId, UserId, new_id
from app.platform.settings import Settings
from app.platform.telegram.deeplinks import LinkType, StartLink, encode_start_param
from app.platform.telegram.port import LinkButton
from app.platform.testing.telegram import RecordingTelegramSender
from tests.plugins.identity import accept_rules, insert_user
from tests.plugins.queue import run_queued

pytestmark = pytest.mark.integration

CHAT = -1_001_234_567_890
BOT = "sosedi_test_bot"
CONCIERGE = "moderation.post_concierge_card"
NUDGE = "notifications.notify_no_responses"


class World:
    """Контейнер воркера и записи теста: их задачи в очереди убираются после теста."""

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

    async def user(self) -> UserId:
        async with self.container() as request:
            session = await request.get(AsyncSession)
            user_id = await insert_user(session)
            await accept_rules(session, user_id)
        self.ids.append(user_id)
        return user_id

    async def client(self) -> UserId:
        """Клиент с ботом без тихих часов: доставка в Telegram создаётся в любое время суток."""
        user_id = await self.user()
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

    async def response(self, job_id: UUID, *, review: str, status: str = "submitted") -> None:
        """Отклик строкой: конвейер модерации этим тестам не нужен."""
        performer = await self.user()
        await self.execute(
            "INSERT INTO jobs.responses (id, job_id, performer_id, status, message, price_type,"
            " review) VALUES (:id, :job, :performer, :status, 'Могу сегодня', 'negotiable',"
            " :review)",
            id=new_id(),
            job=job_id,
            performer=performer,
            status=status,
            review=review,
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

    async def waits(self, task: str, job_id: JobId) -> timedelta:
        """Через сколько после публикации задача заявки выполнится (`scheduled_at`)."""
        return await self.scalar(  # type: ignore[no-any-return]
            "SELECT q.scheduled_at - j.published_at FROM procrastinate_jobs q"
            " JOIN jobs.jobs j ON j.id = CAST(q.args->'payload'->>'job_id' AS uuid)"
            " WHERE q.task_name = :task AND q.status = 'todo' AND j.id = :id",
            task=task,
            id=job_id,
        )

    async def concierge(self, job_id: JobId, *, minutes: int = 20) -> RecordingTelegramSender:
        """Задача concierge с настоящими фасадами; чат модераторов — запись вызовов Bot API."""
        sender = RecordingTelegramSender()
        async with self.container() as request:
            clock = await request.get(Clock)
            chat = TelegramModeratorsChat(
                sender, Translator.load(), CHAT, clock=clock, bot_username=BOT
            )
            post = PostConciergeCard(
                await request.get(JobsApi),
                await request.get(CatalogApi),
                await request.get(GeoApi),
                chat,
                clock,
            )
            published = clock.now() - timedelta(minutes=minutes)
            await post(PostConciergeCardCommand(job_id=job_id, published_at=published))
        return sender


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


async def test_publication_schedules_the_concierge_and_the_client_nudge(world: World) -> None:
    client = await world.client()
    job_id = await world.published(client)

    assert await world.waits(CONCIERGE, job_id) == timedelta(minutes=20)
    assert await world.waits(NUDGE, job_id) == timedelta(hours=1)


async def test_job_reach_counts_only_live_responses(world: World) -> None:
    client = await world.client()
    job_id = await world.published(client)
    await world.response(job_id, review="pending")
    await world.response(job_id, review="blocked")
    await world.response(job_id, review="clear", status="withdrawn")
    async with world.container() as request:
        jobs = await request.get(JobsApi)
        before = await jobs.job_reach(job_id)
        await world.response(job_id, review="clear")
        after = await jobs.job_reach(job_id)

    assert before is not None
    assert after is not None
    assert (before.status, before.direct, before.notified_count) == ("published", False, 0)
    assert before.published_at is not None
    assert (before.responses, before.pending_responses) == (0, 1)
    assert (after.responses, after.pending_responses) == (1, 1)


async def test_quiet_job_card_goes_to_the_moderators_chat(world: World) -> None:
    client = await world.client()
    job_id = await world.published(client)
    await world.execute("UPDATE jobs.jobs SET notified_count = 4 WHERE id = :id", id=job_id)

    sender = await world.concierge(job_id)

    [card] = sender.sent
    link = f"https://t.me/{BOT}?startapp=" + encode_start_param(
        StartLink(type=LinkType.JOB, id=job_id)
    )
    assert card.chat_id == CHAT
    assert "<b>Повесить люстру в спальне</b>" in card.text
    assert "Нови-Сад" in card.text
    assert "0 откликов за 20 мин · разослано подписчикам: 4" in card.text
    assert link in card.text
    assert card.buttons == (LinkButton(text="Открыть заявку", url=link),)


async def test_answered_or_closed_job_is_not_a_concierge_case(world: World) -> None:
    client = await world.client()
    answered = await world.published(client)
    await world.response(answered, review="clear")
    closed = await world.published(client)
    await world.execute("UPDATE jobs.jobs SET status = 'closed' WHERE id = :id", id=closed)

    assert (await world.concierge(answered)).sent == []
    assert (await world.concierge(closed)).sent == []


async def test_client_hears_once_that_nobody_has_responded(world: World) -> None:
    client = await world.client()
    job_id = await world.published(client)

    assert await run_queued(world.container, NUDGE, user_id=job_id, by="job_id") == 1

    [notification] = await world.notifications(client)
    assert (notification["type"], notification["in_app"]) == ("job.no_responses", False)
    assert notification["delivery"] == "queued"
    assert notification["payload"]["params"] == {
        "job_id": str(job_id),
        "title": "Повесить люстру в спальне",
    }
    assert notification["payload"]["link"] == encode_start_param(
        StartLink(type=LinkType.JOB, id=job_id)
    )
    assert notification["payload"]["valid_until"] is not None
    # повторная публикация (продление истёкшей) — второго сообщения нет
    again = JobPublished(
        job_id=job_id,
        client_id=client,
        category_id=CategoryId(1),
        city_id=CityId(1),
        urgency="this_week",
        republished=True,
        occurred_at=datetime.now(UTC),
    )
    async with world.container() as request:
        await notify_no_responses(again, await request.get(Notify), await request.get(JobsApi))
    assert len(await world.notifications(client)) == 1


async def test_client_is_not_nudged_once_someone_responded(world: World) -> None:
    client = await world.client()
    job_id = await world.published(client)
    await world.response(job_id, review="pending")  # клиент его ещё не видит, но отклик есть

    assert await run_queued(world.container, NUDGE, user_id=job_id, by="job_id") == 1

    assert await world.notifications(client) == []
