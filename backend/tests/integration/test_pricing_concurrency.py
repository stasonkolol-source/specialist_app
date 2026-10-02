"""Параллельное добавление позиций: лимит прайса и порядок сохраняются под гонкой."""

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import make_worker_container
from app.modules.pricing.application.ports import ServiceRepository
from app.modules.pricing.application.use_cases.add_service import AddService, AddServiceCommand
from app.modules.pricing.domain.service import MAX_ITEMS, PriceType, Service
from app.modules.pricing.errors import PriceListFullError
from app.modules.specialists.application.use_cases.create_profile import (
    CreateProfile,
    CreateProfileCommand,
)
from app.modules.specialists.domain.profile import ProfileKind
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import SystemClock
from app.platform.kernel.ids import CityId, UserId
from app.platform.settings import Settings
from tests.plugins.identity import accept_rules, insert_user

pytestmark = pytest.mark.integration


@pytest.fixture
async def container(settings: Settings, geo_seeded: None) -> AsyncIterator[AsyncContainer]:
    container = make_worker_container(settings)
    try:
        yield container
    finally:
        await container.close()


async def profile(container: AsyncContainer) -> tuple[UserId, UUID]:
    async with container() as request:
        session = await request.get(AsyncSession)
        user_id = await insert_user(session)
        await accept_rules(session, user_id)
        city = await session.scalar(text("SELECT id FROM geo.cities WHERE slug = 'novi-sad'"))
        created = await (await request.get(CreateProfile))(
            CreateProfileCommand(actor_id=user_id, kind=ProfileKind.PRO, city_id=CityId(city))
        )
    return user_id, created.id


async def add_service(container: AsyncContainer, user_id: UserId) -> Service | PriceListFullError:
    async with container() as request:
        try:
            return await (await request.get(AddService))(
                AddServiceCommand(
                    actor_id=user_id, title="Вторая позиция", price_type=PriceType.NEGOTIABLE
                )
            )
        except PriceListFullError as error:
            return error


async def wait_for_read(
    engine: AsyncEngine, blocker: int, task: asyncio.Task[Service | PriceListFullError]
) -> None:
    """Второй запрос либо ждёт первую транзакцию в БД, либо уже обошёл её блокировку."""
    async with asyncio.timeout(10), engine.connect() as connection:
        while not task.done():
            waiting = await connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity"
                    " WHERE :pid = ANY(pg_blocking_pids(pid)))"
                ),
                {"pid": blocker},
            )
            if waiting:
                return
            await connection.rollback()
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("existing", [0, MAX_ITEMS - 1])
async def test_concurrent_add_preserves_limit_and_positions(
    container: AsyncContainer, existing: int
) -> None:
    user_id, profile_id = await profile(container)
    engine = await container.get(AsyncEngine)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO pricing.services (id, profile_id, title, price_type, position)"
                " SELECT uuidv7(), :profile, 'Услуга', 'negotiable', position"
                " FROM generate_series(0, :last) AS position"
            ),
            {"profile": profile_id, "last": existing - 1},
        )

    second: asyncio.Task[Service | PriceListFullError] | None = None
    try:
        async with container() as request:
            uow = await request.get(UnitOfWork)
            services = await request.get(ServiceRepository)
            session = await request.get(AsyncSession)
            async with uow:
                current = await services.list_for_update(profile_id)
                assert len(current) == existing
                blocker = await session.scalar(text("SELECT pg_backend_pid()"))
                await services.add(
                    Service.add(
                        profile_id=profile_id,
                        title="Первая позиция",
                        price_type=PriceType.NEGOTIABLE,
                        now=SystemClock().now(),
                        position=len(current),
                    )
                )
                second = asyncio.create_task(add_service(container, user_id))
                await wait_for_read(engine, blocker, second)

        result = await asyncio.wait_for(second, timeout=10)
        if existing == MAX_ITEMS - 1:
            assert isinstance(result, PriceListFullError)
        else:
            assert isinstance(result, Service)
            assert result.position == 1

        async with engine.connect() as connection:
            positions = (
                await connection.scalars(
                    text(
                        "SELECT position FROM pricing.services"
                        " WHERE profile_id = :profile AND deleted_at IS NULL ORDER BY position"
                    ),
                    {"profile": profile_id},
                )
            ).all()
        assert positions == list(range(min(existing + 2, MAX_ITEMS)))
    finally:
        if second is not None:
            second.cancel()
            await asyncio.gather(second, return_exceptions=True)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM procrastinate_jobs WHERE status = 'todo'"
                    " AND args->'payload'->>'user_id' = :id"
                ),
                {"id": str(user_id)},
            )
