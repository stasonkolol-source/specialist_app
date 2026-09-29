"""Аналитика на настоящей очереди (DEVELOPMENT_PLAN 1.7): событие уходит только после commit
и не уходит при rollback; подписчики платформы подключены в каждом процессе."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from dishka import AsyncContainer
from sqlalchemy.ext.asyncio import AsyncSession

from app.entrypoints._wiring import make_web_container, make_worker_container
from app.platform.analytics.fake import LoggingAnalytics
from app.platform.analytics.port import Analytics
from app.platform.analytics.tasks import CAPTURE_USER_REGISTERED
from app.platform.contracts.events.identity import EntryPoint, UserRegistered
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId, new_id
from app.platform.queue.dispatcher import EventRegistry
from app.platform.settings import Settings
from tests.plugins.identity import insert_user
from tests.plugins.queue import run_queued

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


@pytest.fixture
async def worker(settings: Settings) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(settings)
    try:
        yield container
    finally:
        await container.close()


async def registered_in_transaction(
    container: AsyncContainer, user_id: UserId, *, fail: bool
) -> None:
    """UserRegistered в транзакции UoW, как его публикует identity; fail — откат."""
    async with container() as request:
        uow = await request.get(UnitOfWork)
        try:
            async with uow:
                uow.add_event(
                    UserRegistered(
                        user_id=user_id,
                        provider="telegram",
                        entry_point=EntryPoint.BOT,
                        start_param="s_02yBkPi1NksSnHWzckDH0V_rAB12CD",
                        occurred_at=NOW,
                    )
                )
                if fail:
                    raise RuntimeError("rollback")
        except RuntimeError:
            pass


async def user(container: AsyncContainer) -> UserId:
    async with container() as request:
        session = await request.get(AsyncSession)
        user_id = await insert_user(session)
        await session.commit()
        return user_id


async def test_event_is_captured_only_after_commit(worker: AsyncContainer) -> None:
    analytics = await worker.get(Analytics)
    assert isinstance(analytics, LoggingAnalytics)  # без ключа PostHog — фейк (dev, тесты)
    committed, rolled_back = await user(worker), await user(worker)

    await registered_in_transaction(worker, committed, fail=False)
    await registered_in_transaction(worker, rolled_back, fail=True)

    assert await run_queued(worker, CAPTURE_USER_REGISTERED, user_id=committed) == 1
    assert await run_queued(worker, CAPTURE_USER_REGISTERED, user_id=rolled_back) == 0
    captured = [e for e in analytics.captured if e.distinct_id in {committed, rolled_back}]
    assert [(e.name, e.distinct_id, dict(e.properties)) for e in captured] == [
        (
            "user_registered",
            committed,
            {"source": "specialist", "entry_point": "bot", "has_referral": True},
        )
    ]


async def test_web_process_also_publishes_to_analytics(settings: Settings) -> None:
    """Подписчики платформы — в реестре событий каждого процесса, а не только воркера:
    иначе событие из web (вход Mini App) не поставило бы задачу аналитики."""
    container = make_web_container(settings)
    try:
        registry = await container.get(EventRegistry)
    finally:
        await container.close()
    event = UserRegistered(user_id=UserId(new_id()), provider="telegram", occurred_at=NOW)

    assert CAPTURE_USER_REGISTERED.name in {t.name for t in registry.subscribers(event)}
