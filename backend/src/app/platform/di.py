"""Провайдер платформы для dishka (ADR-0020 §7).

Синглтон — только объект со Scope.APP: он создаётся один раз на процесс и закрывается
при остановке. REQUEST — всё, что живёт одну команду: сессия, UoW, очередь.
Провайдеры внешних клиентов добавляют их шаги: ключи JWT (0.14), Bot (0.22), S3 (0.24),
переводы (1.2), AI (2.4), аналитика (1.7).
"""

from collections.abc import AsyncIterator

import procrastinate
from dishka import Provider, Scope, from_context, provide
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.platform.db.engine import libpq_dsn, make_engine, make_session_maker
from app.platform.db.port import UnitOfWork
from app.platform.db.uow import SqlAlchemyUnitOfWork
from app.platform.kernel.clock import Clock, SystemClock
from app.platform.queue.dispatcher import EventDispatcher, EventRegistry
from app.platform.queue.port import JobQueue
from app.platform.queue.procrastinate_queue import ProcrastinateJobQueue
from app.platform.settings import (
    AiSettings,
    AnalyticsSettings,
    AppSettings,
    DbSettings,
    JwtSettings,
    S3Settings,
    SentrySettings,
    Settings,
    TelegramSettings,
    ValkeySettings,
)


class PlatformProvider(Provider):
    settings = from_context(provides=Settings, scope=Scope.APP)
    registry = from_context(provides=EventRegistry, scope=Scope.APP)

    # --- группы настроек (APP) ------------------------------------------------------------

    @provide(scope=Scope.APP)
    def app_settings(self, s: Settings) -> AppSettings:
        return s.app

    @provide(scope=Scope.APP)
    def db_settings(self, s: Settings) -> DbSettings:
        return s.db

    @provide(scope=Scope.APP)
    def valkey_settings(self, s: Settings) -> ValkeySettings:
        return s.valkey

    @provide(scope=Scope.APP)
    def telegram_settings(self, s: Settings) -> TelegramSettings:
        return s.telegram

    @provide(scope=Scope.APP)
    def jwt_settings(self, s: Settings) -> JwtSettings:
        return s.jwt

    @provide(scope=Scope.APP)
    def s3_settings(self, s: Settings) -> S3Settings:
        return s.s3

    @provide(scope=Scope.APP)
    def sentry_settings(self, s: Settings) -> SentrySettings:
        return s.sentry

    @provide(scope=Scope.APP)
    def ai_settings(self, s: Settings) -> AiSettings:
        return s.ai

    @provide(scope=Scope.APP)
    def analytics_settings(self, s: Settings) -> AnalyticsSettings:
        return s.analytics

    # --- синглтоны процесса (APP) ---------------------------------------------------------

    @provide(scope=Scope.APP)
    async def engine(self, db: DbSettings) -> AsyncIterator[AsyncEngine]:
        engine = make_engine(db)
        yield engine
        await engine.dispose()

    @provide(scope=Scope.APP)
    def session_maker(self, engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
        return make_session_maker(engine)

    @provide(scope=Scope.APP)
    async def valkey(self, settings: ValkeySettings) -> AsyncIterator[Redis]:
        client = Redis.from_url(settings.url.get_secret_value())
        yield client
        await client.aclose()

    @provide(scope=Scope.APP)
    async def procrastinate_app(self, db: DbSettings) -> AsyncIterator[procrastinate.App]:
        connector = procrastinate.PsycopgConnector(
            conninfo=libpq_dsn(db.dsn.get_secret_value()), min_size=1, max_size=4
        )
        app = procrastinate.App(connector=connector)
        async with app.open_async():
            yield app

    clock = provide(SystemClock, scope=Scope.APP, provides=Clock)

    # --- одна команда (REQUEST) -----------------------------------------------------------

    @provide(scope=Scope.REQUEST)
    async def session(self, maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    @provide(scope=Scope.REQUEST)
    def job_queue(self, session: AsyncSession, app: procrastinate.App) -> JobQueue:
        return ProcrastinateJobQueue(session, app)

    @provide(scope=Scope.REQUEST)
    def dispatcher(self, registry: EventRegistry, queue: JobQueue) -> EventDispatcher:
        return EventDispatcher(registry, queue)

    uow = provide(SqlAlchemyUnitOfWork, scope=Scope.REQUEST, provides=UnitOfWork)
