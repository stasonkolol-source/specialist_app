"""Движок и транзакция на тест с откатом (ADR-0020 §11).

`db_connection` открывает внешнюю транзакцию, а сессии внутри теста работают
на savepoint'ах: commit в коде теста не выходит за пределы теста, в конце — rollback.
"""

from collections.abc import AsyncIterator

import procrastinate
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.platform.db.uow import SqlAlchemyUnitOfWork
from app.platform.queue.dispatcher import EventDispatcher, EventRegistry
from app.platform.queue.procrastinate_queue import ProcrastinateJobQueue
from tests.plugins.containers import PostgresInfo


def make_uow(
    session: AsyncSession, app: procrastinate.App, registry: EventRegistry | None = None
) -> SqlAlchemyUnitOfWork:
    """UoW как в проде: диспетчер событий ставит задачи через Procrastinate в той же транзакции."""
    queue = ProcrastinateJobQueue(session, app)
    return SqlAlchemyUnitOfWork(session, EventDispatcher(registry or EventRegistry(), queue))


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def procrastinate_app(postgres: PostgresInfo) -> AsyncIterator[procrastinate.App]:
    connector = procrastinate.PsycopgConnector(
        conninfo=postgres.dsn("app", driver="postgresql"), min_size=1, max_size=4
    )
    app = procrastinate.App(connector=connector)
    async with app.open_async():
        yield app


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_engine(postgres: PostgresInfo) -> AsyncIterator[AsyncEngine]:
    """Движок под ролью app — как у процессов приложения."""
    engine = create_async_engine(postgres.dsn("app"), pool_size=5)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def migrator_engine(postgres: PostgresInfo) -> AsyncIterator[AsyncEngine]:
    """Движок под ролью migrator — для миграций и подготовки схем в тестах."""
    engine = create_async_engine(postgres.dsn("migrator"), pool_size=2)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def db_connection(db_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()


@pytest_asyncio.fixture(loop_scope="session")
async def db_session(db_connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    maker = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    async with maker() as session:
        yield session


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
