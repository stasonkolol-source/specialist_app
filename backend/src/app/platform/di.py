"""Провайдер платформы для dishka (ADR-0020 §7).

Синглтон — только объект со Scope.APP: он создаётся один раз на процесс и закрывается
при остановке. REQUEST — всё, что живёт одну команду: сессия, UoW, очередь.
Провайдеры внешних клиентов добавляют их шаги: AI (2.4).
Правовые тексты (1.5a) читаются из файлов репозитория один раз на процесс.
"""

from collections.abc import AsyncIterator, Iterator
from datetime import timedelta

import httpx
import procrastinate
from aiogram import Bot
from dishka import Provider, Scope, from_context, provide
from limits.aio.storage import RedisStorage
from limits.aio.strategies import SlidingWindowCounterRateLimiter
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.platform.analytics.fake import LoggingAnalytics
from app.platform.analytics.port import Analytics
from app.platform.analytics.posthog import PostHogAnalytics
from app.platform.audit.port import AuditLog
from app.platform.audit.sql import SqlAuditLog
from app.platform.config.cache import ClientConfigCache
from app.platform.config.port import FeatureFlags, LegalVersions
from app.platform.db.engine import libpq_dsn, make_engine, make_session_maker
from app.platform.db.port import UnitOfWork
from app.platform.db.uow import SqlAlchemyUnitOfWork
from app.platform.i18n.translator import Translator
from app.platform.idempotency.port import IdempotencyStore
from app.platform.idempotency.sql import SqlIdempotencyStore
from app.platform.kernel.clock import Clock, SystemClock
from app.platform.legal.files import FileLegalLibrary, placeholders
from app.platform.legal.port import LegalLibrary
from app.platform.queue.dispatcher import EventDispatcher, EventRegistry
from app.platform.queue.port import JobQueue
from app.platform.queue.procrastinate_queue import ProcrastinateJobQueue
from app.platform.ratelimit import RateLimiter
from app.platform.security.denylist import SessionDenylist
from app.platform.security.initdata import InitDataVerifier
from app.platform.security.jwt import AccessTokens, JwtKeys, JwtKeysError
from app.platform.settings import (
    AiSettings,
    AnalyticsSettings,
    AppSettings,
    DbSettings,
    JwtSettings,
    LegalSettings,
    S3Settings,
    SentrySettings,
    Settings,
    TelegramSettings,
    ValkeySettings,
)
from app.platform.storage.port import StoragePort
from app.platform.storage.s3 import S3Storage
from app.platform.telegram.texts import BOT_DEFAULTS

ANALYTICS_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class PlatformProvider(Provider):
    settings = from_context(provides=Settings, scope=Scope.APP)
    registry = from_context(provides=EventRegistry, scope=Scope.APP)
    translator = from_context(provides=Translator, scope=Scope.APP)

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

    @provide(scope=Scope.APP)
    def legal_settings(self, s: Settings) -> LegalSettings:
        return s.legal

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

    @provide(scope=Scope.APP)
    async def telegram_bot(self, settings: TelegramSettings) -> AsyncIterator[Bot]:
        """Клиент Bot API окружения: один на процесс, сессия закрывается при остановке."""
        # тексты бота — HTML (platform/telegram/texts.py): <b>, переносы; параметры экранированы
        bot = Bot(settings.bot_token.get_secret_value(), default=BOT_DEFAULTS)
        yield bot
        await bot.session.close()

    @provide(scope=Scope.APP)
    def storage(self, settings: S3Settings, clock: Clock) -> Iterator[StoragePort]:
        """S3/R2: клиенты boto3 создаются при первом запросе порта (без ключей — ошибка)."""
        storage = S3Storage(settings, clock)
        yield storage
        storage.close()

    @provide(scope=Scope.APP)
    async def analytics(
        self, settings: AnalyticsSettings, app: AppSettings
    ) -> AsyncIterator[Analytics]:
        """PostHog EU, если есть ключ (K32); без ключа — события в лог (dev, тесты)."""
        if settings.posthog_api_key is None:
            yield LoggingAnalytics()
            return
        async with httpx.AsyncClient(timeout=ANALYTICS_TIMEOUT) as client:
            yield PostHogAnalytics(
                client,
                api_key=settings.posthog_api_key,
                host=settings.posthog_host,
                environment=app.env.value,
            )

    @provide(scope=Scope.APP)
    def client_config(self, maker: async_sessionmaker[AsyncSession]) -> ClientConfigCache:
        return ClientConfigCache(maker)

    @provide(scope=Scope.APP)
    def feature_flags(self, cache: ClientConfigCache) -> FeatureFlags:
        return cache

    @provide(scope=Scope.APP)
    def legal_versions(self, cache: ClientConfigCache) -> LegalVersions:
        return cache

    @provide(scope=Scope.APP)
    def legal_library(self, app: AppSettings, legal: LegalSettings) -> LegalLibrary:
        """Тексты правовых документов: читаются и проверяются один раз на процесс."""
        return FileLegalLibrary(placeholders(app, legal))

    @provide(scope=Scope.APP)
    def init_data_verifier(self, telegram: TelegramSettings, clock: Clock) -> InitDataVerifier:
        return InitDataVerifier(telegram.bot_token, clock)

    @provide(scope=Scope.APP)
    def access_tokens(self, settings: JwtSettings, clock: Clock) -> AccessTokens:
        if settings.keys is None:
            raise JwtKeysError("JWT_KEYS is not set: run `make cli ARGS=jwt-keys`")
        return AccessTokens(
            JwtKeys.parse(settings.keys.get_secret_value()),
            clock,
            issuer=settings.issuer,
            ttl=timedelta(seconds=settings.access_ttl_seconds),
        )

    @provide(scope=Scope.APP)
    def session_denylist(self, valkey: Redis, settings: JwtSettings) -> SessionDenylist:
        return SessionDenylist(valkey, ttl=timedelta(seconds=settings.access_ttl_seconds))

    @provide(scope=Scope.APP)
    def rate_limiter(self, valkey: Redis, settings: ValkeySettings, clock: Clock) -> RateLimiter:
        """Лимитер на пуле соединений общего клиента Valkey."""
        storage = RedisStorage(
            f"async+{settings.url.get_secret_value()}",
            implementation="redispy",
            key_prefix="rl",
            wrap_exceptions=True,
            connection_pool=valkey.connection_pool,  # type: ignore[arg-type]  # limits: **options
        )
        return RateLimiter(SlidingWindowCounterRateLimiter(storage), valkey, clock)

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
    audit_log = provide(SqlAuditLog, scope=Scope.REQUEST, provides=AuditLog)
    idempotency = provide(SqlIdempotencyStore, scope=Scope.REQUEST, provides=IdempotencyStore)
