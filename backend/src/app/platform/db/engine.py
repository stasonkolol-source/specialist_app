"""Движок и фабрика сессий (ADR-0004, ADR-0020 §4, §7). Создаются в DI со Scope.APP."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.platform.settings import DbSettings


def make_engine(settings: DbSettings, *, application_name: str = "sosed") -> AsyncEngine:
    """Engine на psycopg 3. Параметры сеанса (таймауты, plan_cache_mode) задаёт роль app в БД."""
    return create_async_engine(
        settings.dsn.get_secret_value(),
        pool_size=settings.pool_size,
        max_overflow=settings.pool_max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=settings.echo,
        connect_args={"application_name": application_name},
    )


def make_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """expire_on_commit=False: после commit атрибуты не истекают (иначе MissingGreenlet)."""
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def warm_up(engine: AsyncEngine, connections: int = 2) -> None:
    """Открыть несколько соединений при старте: первый запрос не платит за handshake."""

    async def ping() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    await asyncio.gather(*(ping() for _ in range(max(1, connections))))
