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
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.principal import Principal
from app.platform.queue.port import JobQueue
from app.platform.settings import GROUPS, Settings, env_names
from tests.plugins.containers import PostgresInfo

pytestmark = pytest.mark.integration


@pytest.fixture
def settings(postgres: PostgresInfo, valkey_url: str, monkeypatch: pytest.MonkeyPatch) -> Settings:
    for group in GROUPS:
        for name in env_names(group):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DB_DSN", postgres.dsn("app"))
    monkeypatch.setenv("VALKEY_URL", valkey_url)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "8123456789:AAE" + "x" * 32)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "sosed_test_bot")
    return Settings(env_file=None)


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
