"""Фикстуры модуля-образца: схема, сессии, UoW как в проде."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import procrastinate
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.platform.db.uow import SqlAlchemyUnitOfWork
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import UserId
from app.platform.kernel.localized import Locale, LocalizedText
from app.platform.kernel.money import Money
from app.platform.queue.dispatcher import EventRegistry
from tests.integration.db.sample import (
    ON_WIDGET_PUBLISHED,
    SCHEMA,
    Base,
    SqlWidgetRepository,
    Widget,
    WidgetPublished,
)
from tests.plugins.database import make_uow

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
LIMAN = GeoPoint(lat=45.2445, lon=19.8395)


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def sample_schema(migrator_engine: AsyncEngine) -> AsyncIterator[None]:
    async with migrator_engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with migrator_engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA {SCHEMA} CASCADE"))


@pytest_asyncio.fixture(loop_scope="session")
async def maker(
    sample_schema: None, db_engine: AsyncEngine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield async_sessionmaker(db_engine, expire_on_commit=False, autoflush=False)
    async with db_engine.begin() as conn:
        await conn.execute(text("DELETE FROM procrastinate_jobs"))
        await conn.execute(text(f"DELETE FROM {SCHEMA}.status_history"))
        await conn.execute(text(f"DELETE FROM {SCHEMA}.widget_parts"))
        await conn.execute(text(f"DELETE FROM {SCHEMA}.widgets"))


@pytest.fixture
def registry() -> EventRegistry:
    reg = EventRegistry()
    reg.subscribe(WidgetPublished, ON_WIDGET_PUBLISHED)
    return reg


@dataclass
class Scope:
    """Один «запрос»: сессия, UoW и репозиторий из одного REQUEST scope."""

    session: AsyncSession
    uow: SqlAlchemyUnitOfWork
    repo: SqlWidgetRepository


@pytest.fixture
def scope_factory(
    maker: async_sessionmaker[AsyncSession],
    procrastinate_app: procrastinate.App,
    registry: EventRegistry,
):  # type: ignore[no-untyped-def]
    def build(session: AsyncSession) -> Scope:
        uow = make_uow(session, procrastinate_app, registry)
        return Scope(session=session, uow=uow, repo=SqlWidgetRepository(session, uow))

    return build


def make_widget(owner: UserId, title: str = "Люстра") -> Widget:
    return Widget.create(
        owner_id=owner,
        title=title,
        name=LocalizedText({Locale.RU: "Люстра", Locale.SR_LATN: "Luster"}),
        price=Money.rsd(5000),
        location=LIMAN,
    )


__all__ = ["LIMAN", "NOW", "Scope", "make_widget", "procrastinate"]
