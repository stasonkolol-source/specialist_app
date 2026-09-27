"""Спайк 0.8: транзакционная постановка задач Procrastinate (ADR-0008, ADR-0020 §4).

Задача ставится на соединении сессии SQLAlchemy — в той же транзакции, что и данные.
Схема Procrastinate живёт в своей схеме `procrastinate`: объекты создаёт migrator,
роль app видит их через search_path. Итог — docs/spikes/0.8-procrastinate-tx.md.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import procrastinate
import psycopg
import pytest
import pytest_asyncio
from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests.plugins.containers import PostgresInfo

pytestmark = pytest.mark.integration

SEARCH_PATH = "public,procrastinate"
DONE: list[int] = []


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def procrastinate_schema(migrator_engine: AsyncEngine) -> AsyncIterator[None]:
    """migrator применяет SQL Procrastinate в схему procrastinate (как сделает миграция 0.9)."""
    schema_sql = procrastinate.schema.SchemaManager.get_schema()
    async with migrator_engine.connect() as conn:
        raw = (await conn.get_raw_connection()).driver_connection
        assert raw is not None
        # SET LOCAL: соединение вернётся в общий пул — session-level SET там бы остался
        async with raw.transaction(), raw.cursor() as cur:
            await cur.execute("CREATE SCHEMA IF NOT EXISTS procrastinate")
            await cur.execute("SET LOCAL search_path TO procrastinate")
            await cur.execute(schema_sql)
            await cur.execute("CREATE SCHEMA IF NOT EXISTS spike_tx")
            await cur.execute("CREATE TABLE IF NOT EXISTS spike_tx.orders (id int PRIMARY KEY)")
        await conn.commit()
    yield
    async with migrator_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA spike_tx CASCADE"))
        await conn.execute(text("DROP SCHEMA procrastinate CASCADE"))


@pytest_asyncio.fixture(loop_scope="session")
async def app(
    procrastinate_schema: None, postgres: PostgresInfo
) -> AsyncIterator[procrastinate.App]:
    connector = procrastinate.PsycopgConnector(
        conninfo=postgres.dsn("app", driver="postgresql"),
        kwargs={"options": f"-c search_path={SEARCH_PATH}"},
        min_size=1,
        max_size=4,
    )
    app = procrastinate.App(connector=connector)

    @app.task(name="spike.record_order", queue="spike", queueing_lock=None)
    async def record_order(order_id: int) -> None:
        DONE.append(order_id)

    async with app.open_async():
        yield app


@pytest_asyncio.fixture(loop_scope="session")
async def session_maker(
    procrastinate_schema: None, postgres: PostgresInfo
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        postgres.dsn("app"), connect_args={"options": f"-c search_path={SEARCH_PATH}"}
    )
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _driver_connection(session: AsyncSession) -> psycopg.AsyncConnection[Any]:
    conn = await session.connection()
    raw = await conn.get_raw_connection()
    driver = raw.driver_connection
    assert isinstance(driver, psycopg.AsyncConnection)
    return driver


async def _count_jobs(app: procrastinate.App) -> int:
    rows = await app.connector.execute_query_all_async(
        "SELECT count(*) AS n FROM procrastinate_jobs WHERE task_name = 'spike.record_order'"
    )
    return int(rows[0]["n"])


async def _cleanup(app: procrastinate.App, session_maker: async_sessionmaker[AsyncSession]) -> None:
    await app.connector.execute_query_async("DELETE FROM procrastinate_jobs")
    async with session_maker() as s:
        await s.execute(text("DELETE FROM spike_tx.orders"))
        await s.commit()
    DONE.clear()


async def test_rollback_removes_data_and_job(
    app: procrastinate.App, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    await _cleanup(app, session_maker)
    task = app.tasks["spike.record_order"]
    async with session_maker() as session:
        await session.execute(text("INSERT INTO spike_tx.orders VALUES (1)"))
        await task.configure(connection=await _driver_connection(session)).defer_async(order_id=1)
        await session.rollback()
    assert await _count_jobs(app) == 0
    async with session_maker() as session:
        assert (await session.execute(text("SELECT count(*) FROM spike_tx.orders"))).scalar() == 0


async def test_commit_makes_job_visible_to_worker_with_notify(
    app: procrastinate.App, session_maker: async_sessionmaker[AsyncSession], postgres: PostgresInfo
) -> None:
    await _cleanup(app, session_maker)
    task = app.tasks["spike.record_order"]
    listener = await psycopg.AsyncConnection.connect(
        postgres.dsn("app", driver="postgresql"), autocommit=True
    )
    try:
        await listener.execute('LISTEN "procrastinate_any_queue_v1"')
        async with session_maker() as session:
            await session.execute(text("INSERT INTO spike_tx.orders VALUES (2)"))
            await task.configure(connection=await _driver_connection(session)).defer_async(
                order_id=2
            )
            # до commit задачу не видит никто — ни пул Procrastinate, ни воркер
            assert await _count_jobs(app) == 0
            await session.commit()
        notify = await asyncio.wait_for(anext(listener.notifies()), timeout=5)
        assert notify.channel == "procrastinate_any_queue_v1"
    finally:
        await listener.close()
    assert await _count_jobs(app) == 1
    await app.run_worker_async(queues=["spike"], wait=False, install_signal_handlers=False)
    assert DONE == [2]


async def test_queueing_lock_under_savepoint_keeps_business_transaction(
    app: procrastinate.App, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    await _cleanup(app, session_maker)
    task = app.tasks["spike.record_order"]
    async with session_maker() as session:
        await session.execute(text("INSERT INTO spike_tx.orders VALUES (3)"))
        driver = await _driver_connection(session)
        for _ in range(2):
            # Адаптер JobQueue ставит каждую задачу под savepoint psycopg — на том же уровне,
            # где Procrastinate выполняет INSERT. AlreadyEnqueued — это успех (задача уже есть).
            try:
                async with driver.transaction():
                    await task.configure(connection=driver, queueing_lock="order-3").defer_async(
                        order_id=3
                    )
            except AlreadyEnqueued:
                pass
        await session.commit()
    assert await _count_jobs(app) == 1
    async with session_maker() as session:
        assert (await session.execute(text("SELECT count(*) FROM spike_tx.orders"))).scalar() == 1


async def test_sqlalchemy_savepoint_is_lazy_and_commit_silently_rolls_back(
    app: procrastinate.App, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """Находка спайка (опасно):
    1) session.begin_nested() не отправляет SAVEPOINT, пока внутри не выполнится команда
       самого SQLAlchemy, — вставка Procrastinate мимо него идёт без savepoint;
    2) после ошибки транзакция в состоянии aborted, и COMMIT PostgreSQL превращает в
       ROLLBACK без исключения: «успешный» commit теряет и данные, и задачу.
    Поэтому: savepoint — на уровне psycopg, а UoW перед COMMIT проверяет состояние."""
    await _cleanup(app, session_maker)
    task = app.tasks["spike.record_order"]
    async with session_maker() as session:
        await session.execute(text("INSERT INTO spike_tx.orders VALUES (5)"))
        driver = await _driver_connection(session)
        for _ in range(2):
            savepoint = await session.begin_nested()
            try:
                await task.configure(connection=driver, queueing_lock="order-5").defer_async(
                    order_id=5
                )
                await savepoint.commit()
            except AlreadyEnqueued:
                await savepoint.rollback()
        assert driver.info.transaction_status == psycopg.pq.TransactionStatus.INERROR
        await session.commit()  # исключения нет — но это был ROLLBACK
    assert await _count_jobs(app) == 0
    async with session_maker() as session:
        assert (await session.execute(text("SELECT count(*) FROM spike_tx.orders"))).scalar() == 0


async def test_without_savepoint_already_enqueued_breaks_transaction(
    app: procrastinate.App, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """Почему нужен savepoint: без него ошибка уникальности портит всю транзакцию."""
    await _cleanup(app, session_maker)
    task = app.tasks["spike.record_order"]
    async with session_maker() as session:
        await session.execute(text("INSERT INTO spike_tx.orders VALUES (4)"))
        driver = await _driver_connection(session)
        await task.configure(connection=driver, queueing_lock="order-4").defer_async(order_id=4)
        with pytest.raises(AlreadyEnqueued):
            await task.configure(connection=driver, queueing_lock="order-4").defer_async(order_id=4)
        with pytest.raises(Exception, match="current transaction is aborted"):
            await session.execute(text("SELECT 1"))
        await session.rollback()


async def test_pool_worker_processes_many_jobs(
    app: procrastinate.App, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    await _cleanup(app, session_maker)
    task = app.tasks["spike.record_order"]
    async with session_maker() as session:
        driver = await _driver_connection(session)
        for order_id in range(100, 120):
            await task.configure(connection=driver).defer_async(order_id=order_id)
        await session.commit()
    await app.run_worker_async(
        queues=["spike"], wait=False, concurrency=4, install_signal_handlers=False
    )
    assert sorted(DONE) == list(range(100, 120))
