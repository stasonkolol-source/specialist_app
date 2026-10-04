"""Задержка «публикация → доставка B1» (DEVELOPMENT_PLAN 5.7): p95 < 2 мин на 1 000 подписчиков.

Вручную: `uv run pytest -m bench -k match_latency`. Тысяча исполнителей с подпиской на раздел
заявки и открытым каналом бота; заявка опубликована — `jobs.match_alerts` (SQL §9.6, блокировки,
лимиты), на каждого — `notifications.notify_job_matched` и `notifications.send`. Воркер — пулы как
в проде (default 8, notifications 4). Отправитель — настоящий AiogramTelegramSender с лимитером
Valkey (25 msg/s на бота, 1 msg/s на чат), но вместо Bot API — фейк, который только запоминает
время: так замер упирается в тот же потолок скорости, что и прод (1 000 сообщений — около 40 с).
Задержка — от commit публикации до записи «отправлено»; тест печатает p50, p95 и максимум.
"""

import asyncio
import statistics
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import procrastinate
import pytest
from dishka import AsyncContainer, Provider, Scope, provide
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.entrypoints._wiring import load_module_tasks, make_container
from app.entrypoints.worker import ROLES
from app.interfaces.worker.registration import register_worker_tasks
from app.modules.jobs.application.ports import MATCH_ALERTS
from app.platform.contracts.events.jobs import JobPublished
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CategoryId, CityId, UserId, new_id
from app.platform.queue.port import JobQueue
from app.platform.queue.tasks import CONTAINER_KEY
from app.platform.settings import Settings
from app.platform.telegram.aiogram_sender import AiogramTelegramSender
from app.platform.telegram.limiter import ValkeySendLimiter
from app.platform.telegram.port import TelegramSender

pytestmark = pytest.mark.bench

SUBSCRIBERS = 1_000
TARGET_P95 = 120.0
DEADLINE = 300.0
POOLS = {pool.queue: pool.concurrency for pool in ROLES["worker"]}


class FakeBot:
    """Bot API без сети: «отправка» мгновенная, только время и число вызовов."""

    def __init__(self) -> None:
        self.sent = 0

    async def send_message(self, **_: Any) -> SimpleNamespace:
        self.sent += 1
        return SimpleNamespace(message_id=self.sent)


class BenchProvider(Provider):
    def __init__(self, bot: FakeBot) -> None:
        super().__init__()
        self._bot = bot

    @provide(scope=Scope.APP, override=True)
    def telegram_sender(self, valkey: Redis) -> TelegramSender:
        """Настоящий адаптер и лимитер — фейковый только Bot API."""
        return AiogramTelegramSender(self._bot, ValkeySendLimiter(valkey))  # type: ignore[arg-type]


@pytest.fixture
async def container(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[tuple[AsyncContainer, FakeBot]]:
    bot = FakeBot()
    container = make_container(storage_settings, BenchProvider(bot))
    load_module_tasks()
    register_worker_tasks(await container.get(procrastinate.App))
    try:
        yield container, bot
    finally:
        await container.close()


async def _execute(engine: AsyncEngine, sql: str, **params: object) -> Any:
    async with engine.begin() as conn:
        result = await conn.execute(text(sql), params)
        return result.all() if result.returns_rows else []


async def _seed(engine: AsyncEngine) -> tuple[UserId, Any]:
    """Подписчики с каналом бота и без тихих часов (замер не должен ждать утра) и клиент с
    опубликованной заявкой — строками."""
    [(leaf, section, city, district)] = await _execute(
        engine,
        "SELECT c.id, c.parent_id, ci.id, d.id FROM catalog.categories c, geo.cities ci,"
        " geo.districts d WHERE c.id = (SELECT min(id) FROM catalog.categories"
        " WHERE is_active AND jobs_enabled AND risk_level = 0 AND parent_id IS NOT NULL)"
        " AND ci.slug = 'novi-sad' AND d.slug = 'liman-3'",
    )
    await _execute(
        engine,
        "WITH people AS (INSERT INTO identity.users (id, display_name, version)"
        " SELECT uuidv7(), 'Bench ' || n, 1 FROM generate_series(1, :count) n RETURNING id),"
        " channels AS (INSERT INTO notifications.channels"
        " (id, user_id, kind, address, granted_via, granted_at)"
        " SELECT uuidv7(), id, 'telegram', (7000000000 + row_number() OVER ())::text,"
        " 'bot_start', now() FROM people RETURNING user_id),"
        " quiet AS (INSERT INTO notifications.user_settings (user_id, quiet_enabled)"
        " SELECT user_id, false FROM channels RETURNING user_id)"
        " INSERT INTO jobs.alerts (id, user_id, category_ids, city_id)"
        " SELECT uuidv7(), user_id, ARRAY[:section], :city FROM quiet",
        count=SUBSCRIBERS,
        section=section,
        city=city,
    )
    client = UserId(new_id())
    await _execute(
        engine,
        "INSERT INTO identity.users (id, display_name, version) VALUES (:id, 'Клиент', 1)",
        id=client,
    )
    job_id = new_id()
    await _execute(
        engine,
        "INSERT INTO jobs.jobs (id, client_id, status, title, description, content_lang,"
        " category_id, category_path, urgency, budget_type, budget_min, city_id, district_id,"
        " published_at, expires_at, version) SELECT :id, :client, 'published', 'Повесить люстру',"
        " '', 'ru', c.id, c.path, 'today', 'fixed', 500000, :city, :district, now(),"
        " now() + interval '1 day', 1 FROM catalog.categories c WHERE c.id = :leaf",
        id=job_id,
        client=client,
        city=city,
        district=district,
        leaf=leaf,
    )
    return client, SimpleNamespace(
        job_id=job_id, category_id=CategoryId(leaf), city_id=CityId(city)
    )


async def _run_until_sent(container: AsyncContainer, engine: AsyncEngine, job: Any) -> None:
    """Воркеры, пока все карточки не отправлены: без ожидания воркер выходит, когда готовых
    задач нет, а доставки, отложенные лимитером, ждут своего слота в очереди."""
    app = await container.get(procrastinate.App)
    started = time.monotonic()
    while time.monotonic() - started < DEADLINE:
        await asyncio.gather(
            *(
                app.run_worker_async(
                    queues=[queue],
                    wait=False,
                    concurrency=concurrency,
                    additional_context={CONTAINER_KEY: container},
                )
                for queue, concurrency in POOLS.items()
            )
        )
        [(sent,)] = await _execute(
            engine,
            "SELECT count(*) FROM notifications.deliveries d JOIN notifications.notifications n"
            " ON n.id = d.notification_id WHERE n.dedupe_key LIKE :prefix AND d.status = 'sent'",
            prefix=f"job.matched:{job.job_id}:%",
        )
        if sent >= SUBSCRIBERS:
            return
        await asyncio.sleep(0.2)
    pytest.fail("карточки не ушли за отведённое время")


async def test_match_latency_p95(
    container: tuple[AsyncContainer, FakeBot], capsys: pytest.CaptureFixture[str]
) -> None:
    worker, bot = container
    engine = await worker.get(AsyncEngine)
    client, job = await _seed(engine)
    await _execute(engine, "DELETE FROM procrastinate_jobs WHERE status = 'todo'")

    async with worker() as request:
        uow, queue = await request.get(UnitOfWork), await request.get(JobQueue)
        async with uow:
            await queue.enqueue(
                MATCH_ALERTS,
                JobPublished(
                    job_id=job.job_id,
                    client_id=client,
                    category_id=job.category_id,
                    city_id=job.city_id,
                    urgency="today",
                    occurred_at=datetime.now(UTC),
                ),
            )
    published = datetime.now(UTC)
    started = time.monotonic()
    await _run_until_sent(worker, engine, job)
    elapsed = time.monotonic() - started

    rows = await _execute(
        engine,
        "SELECT d.sent_at FROM notifications.deliveries d JOIN notifications.notifications n"
        " ON n.id = d.notification_id WHERE n.dedupe_key LIKE :prefix AND d.status = 'sent'",
        prefix=f"job.matched:{job.job_id}:%",
    )
    lags = sorted((row.sent_at - published).total_seconds() for row in rows)
    p50 = statistics.median(lags)
    p95 = statistics.quantiles(lags, n=20, method="inclusive")[-1]
    with capsys.disabled():
        print(
            f"\nmatch_latency: {SUBSCRIBERS} подписчиков, {len(lags)} карточек B1 за"
            f" {elapsed:.1f} с (Bot API вызван {bot.sent} раз); p50 {p50:.1f} с,"
            f" p95 {p95:.1f} с, максимум {max(lags):.1f} с (порог p95 {TARGET_P95:.0f} с)"
        )
    assert len(lags) == SUBSCRIBERS
    assert p95 < TARGET_P95
