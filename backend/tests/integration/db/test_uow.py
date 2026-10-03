"""Unit of Work, события и очередь (DEVELOPMENT_PLAN 0.10, ADR-0020 «Что сделать» п. 3)."""

import contextlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Final, cast
from uuid import UUID

import procrastinate
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.platform.db.errors import (
    FailedTransactionError,
    NestedTransactionError,
    UnsavedAggregateError,
    WriteOutsideUnitOfWorkError,
)
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId, new_id
from app.platform.kernel.pagination import PageRequest
from app.platform.queue.port import TaskRef
from app.platform.queue.procrastinate_queue import ProcrastinateJobQueue
from app.platform.testing.queue import queued_tasks
from tests.integration.db.conftest import NOW, Scope, make_widget
from tests.integration.db.sample import (
    ON_WIDGET_PUBLISHED,
    SCHEMA,
    DuplicateWidgetTitleError,
    SqlWidgetQuery,
    WidgetPublished,
    WidgetRow,
)
from tests.plugins.containers import PostgresInfo
from tests.plugins.round_trips import round_trips

pytestmark = pytest.mark.integration

Maker = async_sessionmaker[AsyncSession]
Build = Callable[[AsyncSession], Scope]


@dataclass(frozen=True, slots=True, kw_only=True)
class PingPayload:
    widget_id: UUID


PING: Final = TaskRef("sample.ping", PingPayload)


async def _widget_count(maker: Maker) -> int:
    async with maker() as s:
        return int((await s.execute(text(f"SELECT count(*) FROM {SCHEMA}.widgets"))).scalar_one())


async def _tasks(maker: Maker, name: str | None = None) -> list[str]:
    async with maker() as s:
        return [t.task_name for t in await queued_tasks(s, name)]


async def test_commit_makes_data_and_subscriber_task_visible(
    maker: Maker, scope_factory: Build
) -> None:
    widget = make_widget(UserId(new_id()))
    async with maker() as s:
        sc = scope_factory(s)
        async with sc.uow:
            await sc.repo.add(widget)
            widget.publish(by=widget.owner_id, now=NOW)
            await sc.repo.save(widget)
    assert await _widget_count(maker) == 1
    async with maker() as s:
        tasks = await queued_tasks(s, ON_WIDGET_PUBLISHED.name)
    assert len(tasks) == 1
    assert tasks[0].payload["widget_id"] == str(widget.id)
    assert tasks[0].queueing_lock is not None  # dedup по (задача, event_id)


async def test_rollback_cancels_data_and_task(
    maker: Maker, scope_factory: Build, procrastinate_app: procrastinate.App
) -> None:
    widget = make_widget(UserId(new_id()))
    async with maker() as s:
        sc = scope_factory(s)
        queue = ProcrastinateJobQueue(s, procrastinate_app)
        with pytest.raises(RuntimeError, match="boom"):
            async with sc.uow:
                await sc.repo.add(widget)
                await queue.enqueue(PING, PingPayload(widget_id=widget.id))
                raise RuntimeError("boom")
    assert await _widget_count(maker) == 0
    assert await _tasks(maker) == []


async def test_nested_block_fails(maker: Maker, scope_factory: Build) -> None:
    async with maker() as s:
        sc = scope_factory(s)
        with pytest.raises(NestedTransactionError):
            async with sc.uow, sc.uow:
                pass


async def test_require_active_and_repository_outside_block_fail(
    maker: Maker, scope_factory: Build
) -> None:
    async with maker() as s:
        sc = scope_factory(s)
        with pytest.raises(WriteOutsideUnitOfWorkError):
            sc.uow.require_active()
        with pytest.raises(WriteOutsideUnitOfWorkError):
            await sc.repo.add(make_widget(UserId(new_id())))


async def test_duplicate_dedup_key_does_not_break_business_transaction(
    maker: Maker, scope_factory: Build, procrastinate_app: procrastinate.App
) -> None:
    widget = make_widget(UserId(new_id()))
    async with maker() as s:
        sc = scope_factory(s)
        queue = ProcrastinateJobQueue(s, procrastinate_app)
        async with sc.uow:
            await sc.repo.add(widget)
            for _ in range(3):
                await queue.enqueue(PING, PingPayload(widget_id=widget.id), dedup_key="ping-1")
    assert await _widget_count(maker) == 1
    assert await _tasks(maker, PING.name) == [PING.name]


async def test_next_block_works_after_failed_commit(maker: Maker, scope_factory: Build) -> None:
    owner = UserId(new_id())
    async with maker() as s:
        sc = scope_factory(s)
        with pytest.raises(DuplicateWidgetTitleError):
            async with sc.uow:
                await sc.repo.add(make_widget(owner, "Шкаф"))
                await sc.repo.add(make_widget(owner, "Шкаф"))
        async with sc.uow:  # тот же скоуп, та же сессия
            await sc.repo.add(make_widget(owner, "Полка"))
    async with maker() as s:
        titles = (await s.scalars(select(WidgetRow.title).where(WidgetRow.owner_id == owner))).all()
    assert list(titles) == ["Полка"]


async def test_read_before_block_does_not_interfere(maker: Maker, scope_factory: Build) -> None:
    owner = UserId(new_id())
    async with maker() as s:
        sc = scope_factory(s)
        await s.execute(text("SELECT 1"))  # autobegin: транзакция чтения открыта
        assert s.in_transaction()
        async with sc.uow:
            await sc.repo.add(make_widget(owner))
    assert await _widget_count(maker) == 1


async def test_write_before_block_is_rejected(maker: Maker, scope_factory: Build) -> None:
    async with maker() as s:
        sc = scope_factory(s)
        s.add(WidgetRow(id=new_id(), owner_id=new_id(), title="x", version=1))
        with pytest.raises(WriteOutsideUnitOfWorkError):
            async with sc.uow:
                pass
        s.expunge_all()


async def test_query_service_returns_connection_outside_uow_but_not_inside(
    maker: Maker, scope_factory: Build
) -> None:
    owner = UserId(new_id())
    async with maker() as s:
        sc = scope_factory(s)
        query = SqlWidgetQuery(s)
        await query.list_for_owner(owner, PageRequest())
        assert not s.in_transaction()
        async with sc.uow:
            await sc.repo.add(make_widget(owner))
            page = await query.list_for_owner(owner, PageRequest())
            assert s.in_transaction()  # чтение внутри блока — в его транзакции
            assert len(page.items) == 1


async def test_forgotten_save_raises_and_commits_nothing(
    maker: Maker, scope_factory: Build
) -> None:
    widget = make_widget(UserId(new_id()))
    async with maker() as s:
        sc = scope_factory(s)
        async with sc.uow:
            await sc.repo.add(widget)
    async with maker() as s:
        sc = scope_factory(s)
        with pytest.raises(UnsavedAggregateError, match="Widget"):
            async with sc.uow:
                loaded = await sc.repo.get(widget.id)
                loaded.publish(by=loaded.owner_id, now=NOW)  # save забыли
    assert await _tasks(maker, ON_WIDGET_PUBLISHED.name) == []


async def test_facade_of_lower_module_joins_caller_transaction(
    maker: Maker, scope_factory: Build
) -> None:
    """Фасад нижнего модуля: require_active и та же сессия — атомарно с use case."""

    class NotesFacade:
        def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
            self._session, self._uow = session, uow

        async def add_note(self, widget_id: UUID) -> None:
            self._uow.require_active()
            await self._session.execute(
                text(f"UPDATE {SCHEMA}.widgets SET title = title || ' ✓' WHERE id = :id"),
                {"id": widget_id},
            )

    widget = make_widget(UserId(new_id()))
    async with maker() as s:
        sc = scope_factory(s)
        facade = NotesFacade(s, sc.uow)
        with pytest.raises(WriteOutsideUnitOfWorkError):
            await facade.add_note(widget.id)
        with pytest.raises(RuntimeError):
            async with sc.uow:
                await sc.repo.add(widget)
                await facade.add_note(widget.id)
                raise RuntimeError  # откатывается и запись фасада
        async with sc.uow:
            await sc.repo.add(widget)
            await facade.add_note(widget.id)
    async with maker() as s:
        title = (await s.execute(select(WidgetRow.title).where(WidgetRow.id == widget.id))).scalar()
    assert title == "Люстра ✓"


async def test_swallowed_sql_error_refuses_silent_rollback(
    maker: Maker, scope_factory: Build
) -> None:
    """Находка спайка 0.8: COMMIT в состоянии ошибки молча становится ROLLBACK — UoW не даёт."""
    async with maker() as s:
        sc = scope_factory(s)
        with pytest.raises(FailedTransactionError):
            async with sc.uow:
                await sc.repo.add(make_widget(UserId(new_id())))
                with contextlib.suppress(Exception):  # имитируем проглоченную ошибку SQL
                    await s.execute(text("SELECT 1/0"))
    assert await _widget_count(maker) == 0


async def test_add_event_without_aggregate_is_dispatched(
    maker: Maker, scope_factory: Build
) -> None:
    widget_id, owner = new_id(), new_id()
    async with maker() as s:
        sc = scope_factory(s)
        async with sc.uow:
            sc.uow.add_event(WidgetPublished(widget_id=widget_id, owner_id=owner, occurred_at=NOW))
    assert await _tasks(maker, ON_WIDGET_PUBLISHED.name) == [ON_WIDGET_PUBLISHED.name]


@pytest.fixture
async def single(postgres: PostgresInfo, sample_schema: None) -> AsyncIterator[Maker]:
    """Пул из одного соединения с проверкой при выдаче, как в проде: чтение в AUTOCOMMIT и
    следующий UoW гарантированно делят одно соединение."""
    engine = create_async_engine(
        postgres.dsn("app"), pool_size=1, max_overflow=0, pool_pre_ping=True
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    finally:
        await engine.dispose()


async def test_standalone_read_goes_without_begin_and_rollback(
    single: Maker, scope_factory: Build
) -> None:
    """Перф: чтение вне UoW — проверка соединения и сам запрос, без BEGIN и ROLLBACK на сервер;
    чтение в UoW — в его транзакции, как прежде."""
    owner = UserId(new_id())
    engine = cast(AsyncEngine, single.kw["bind"])
    async with single() as s:
        query = SqlWidgetQuery(s)
        with round_trips(engine) as trips:
            await query.list_for_owner(owner, PageRequest())
            await query.list_for_owner(owner, PageRequest())
        assert not s.in_transaction()
        assert (trips.queries, trips.begins, trips.ends) == (2, 0, 0)
        assert trips.total == 4  # было 8: pre-ping, BEGIN, SELECT, ROLLBACK на каждое чтение
        sc = scope_factory(s)
        with round_trips(engine) as trips:
            async with sc.uow:
                await query.list_for_owner(owner, PageRequest())
                await sc.repo.add(make_widget(owner))
        assert (trips.begins, trips.ends) == (1, 1)


async def test_uow_after_autocommit_read_still_rolls_back(
    single: Maker, scope_factory: Build
) -> None:
    """Пул возвращает соединению обычный уровень изоляции: запись UoW после чтения в
    AUTOCOMMIT на том же соединении откатывается целиком."""
    owner = UserId(new_id())
    async with single() as s:
        await SqlWidgetQuery(s).list_for_owner(owner, PageRequest())
    async with single() as s:
        sc = scope_factory(s)
        with pytest.raises(RuntimeError):
            async with sc.uow:
                await sc.repo.add(make_widget(owner))
                driver = (await s.connection()).sync_connection
                assert driver is not None
                assert driver.connection.driver_connection.autocommit is False
                raise RuntimeError
        await SqlWidgetQuery(s).list_for_owner(owner, PageRequest())
    async with single() as s:
        assert (await SqlWidgetQuery(s).list_for_owner(owner, PageRequest())).items == ()


async def test_failed_standalone_read_leaves_the_session_usable(single: Maker) -> None:
    async with single() as s:
        query = SqlWidgetQuery(s)
        with pytest.raises(DBAPIError):
            await query.boom()
        assert not s.in_transaction()
        assert (await query.list_for_owner(UserId(new_id()), PageRequest())).items == ()
