"""DI-контейнер dishka (DEVELOPMENT_PLAN 0.11, ADR-0020 §7 и «Что сделать» п. 4)."""

import procrastinate
import pytest
from dishka import Provider, Scope, provide
from dishka.exceptions import GraphMissingFactoryError
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.entrypoints._wiring import (
    make_bot_container,
    make_container,
    make_web_container,
    make_worker_container,
)
from app.interfaces.http.warmup import WARM_CONNECTIONS, warm_up_web
from app.platform.config.cache import ClientConfigCache
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.principal import Principal
from app.platform.queue.port import JobQueue
from app.platform.settings import Settings
from tests.plugins.round_trips import round_trips

pytestmark = pytest.mark.integration


class OtherModuleFacade:
    """Фасад «другого модуля»: должен работать в той же сессии, что и use case."""

    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self.session, self.uow = session, uow


class SomeUseCase:
    def __init__(self, session: AsyncSession, uow: UnitOfWork, facade: OtherModuleFacade) -> None:
        self.session, self.uow, self.facade = session, uow, facade


class SampleProvider(Provider):
    scope = Scope.REQUEST
    facade = provide(OtherModuleFacade)
    use_case = provide(SomeUseCase)


async def test_app_scope_objects_are_created_once(settings: Settings) -> None:
    container = make_worker_container(settings)
    try:
        engines, clocks = [], []
        for _ in range(3):
            async with container() as request:
                engines.append(await request.get(AsyncEngine))
                clocks.append(await request.get(Clock))
        assert engines[0] is engines[1] is engines[2]
        assert clocks[0] is clocks[1] is clocks[2]
        assert await container.get(procrastinate.App) is await container.get(procrastinate.App)
        valkey = await container.get(Redis)
        assert await valkey.ping() is True
    finally:
        await container.close()


async def test_use_case_and_facade_share_one_session_per_request(settings: Settings) -> None:
    container = make_container(settings, SampleProvider())
    try:
        async with container() as first:
            use_case = await first.get(SomeUseCase)
            assert use_case.session is use_case.facade.session
            assert use_case.uow is use_case.facade.uow
            assert use_case.session is await first.get(AsyncSession)
            queue = await first.get(JobQueue)
            async with use_case.uow:
                value = (await use_case.session.execute(text("SELECT current_user"))).scalar()
            assert value == "app"
            assert queue is await first.get(JobQueue)
        async with container() as second:
            assert (await second.get(SomeUseCase)).session is not use_case.session
    finally:
        await container.close()


@pytest.mark.parametrize("factory", [make_web_container, make_bot_container, make_worker_container])
async def test_process_containers_build(settings: Settings, factory: object) -> None:
    container = factory(settings)  # type: ignore[operator]
    await container.close()


class NeedsPrincipal:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal


class NeedsPrincipalProvider(Provider):
    needs = provide(NeedsPrincipal, scope=Scope.REQUEST)


def test_worker_has_no_principal_and_fails_at_build(settings: Settings) -> None:
    with pytest.raises(GraphMissingFactoryError, match="Principal"):
        make_container(settings, NeedsPrincipalProvider())


async def test_web_warm_up_opens_connections_and_reads_client_config(settings: Settings) -> None:
    """Перф-аудит: lifespan web открывает соединения с базой и читает client-config до первого
    запроса — первый запрос после рестарта их уже не ждёт."""
    container = make_web_container(settings)
    try:
        await warm_up_web(container)
        engine = await container.get(AsyncEngine)
        assert engine.pool.checkedin() >= WARM_CONNECTIONS  # type: ignore[attr-defined]
        with round_trips(engine) as trips:
            await (await container.get(ClientConfigCache)).get()
        assert trips.queries == 0
    finally:
        await container.close()
