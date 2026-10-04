"""Провайдер платформы для dishka (ADR-0020 §7).

Синглтон — только объект со Scope.APP: он создаётся один раз на процесс и закрывается
при остановке. REQUEST — всё, что живёт одну команду: сессия, UoW, очередь.
AI-проверки (2.4): реальные адаптеры — только с ключом, без него — заглушки (platform/ai/stubs.py).
Правовые тексты (1.5a) читаются из файлов репозитория один раз на процесс.
"""

from collections.abc import AsyncIterator, Iterator
from datetime import timedelta

import anthropic
import httpx
import procrastinate
import structlog
from aiogram import Bot
from dishka import Provider, Scope, from_context, provide
from limits.aio.storage import RedisStorage
from limits.aio.strategies import SlidingWindowCounterRateLimiter
from prometheus_client import CollectorRegistry
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.platform.ai.anthropic_classifier import AnthropicPolicyClassifier
from app.platform.ai.breaker import CircuitBreaker
from app.platform.ai.openai_moderation import OpenAiModeration
from app.platform.ai.port import Moderation, PolicyClassifier, SecondaryImage
from app.platform.ai.stubs import (
    NoModeration,
    NoPolicyClassifier,
    NoSecondaryImage,
    StubModeration,
    StubPolicyClassifier,
)
from app.platform.analytics.deleted import SqlDeletedUsers
from app.platform.analytics.fake import LoggingAnalytics
from app.platform.analytics.port import Analytics, PersonDeletion
from app.platform.analytics.posthog import PostHogAnalytics
from app.platform.analytics.posthog_dashboard import client_for
from app.platform.analytics.posthog_persons import (
    MISSING_KEYS,
    NoPersonDeletion,
    PostHogPersons,
)
from app.platform.audit.port import AuditLog, AuditReader
from app.platform.audit.sql import SqlAuditLog, SqlAuditReader
from app.platform.cache.port import JsonCache
from app.platform.cache.valkey import ValkeyJsonCache
from app.platform.config.cache import ClientConfigCache
from app.platform.config.port import FeatureFlags, LegalVersions
from app.platform.db.engine import libpq_dsn, make_engine, make_session_maker
from app.platform.db.port import UnitOfWork
from app.platform.db.uow import SqlAlchemyUnitOfWork
from app.platform.entitlements.port import Entitlements
from app.platform.entitlements.unlimited import UnlimitedEntitlements
from app.platform.i18n.translator import Translator
from app.platform.idempotency.port import IdempotencyStore
from app.platform.idempotency.sql import SqlIdempotencyStore
from app.platform.kernel.clock import Clock, SystemClock
from app.platform.legal.files import FileLegalLibrary, placeholders
from app.platform.legal.port import LegalLibrary
from app.platform.observability.metrics import (
    HttpMetrics,
    QueueMetrics,
    TelegramMetrics,
    make_queue_metrics,
    make_registry,
)
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
    Environment,
    HealthchecksSettings,
    JwtSettings,
    LegalSettings,
    MetricsSettings,
    S3Settings,
    SentrySettings,
    Settings,
    TelegramSettings,
    ValkeySettings,
)
from app.platform.storage.port import StoragePort
from app.platform.storage.s3 import S3Storage
from app.platform.telegram.aiogram_sender import AiogramTelegramSender
from app.platform.telegram.fake_sender import FakeTelegramSender
from app.platform.telegram.limiter import ValkeySendLimiter
from app.platform.telegram.metrics import FloodWaitMetrics
from app.platform.telegram.port import PreparedMessages, TelegramSender
from app.platform.telegram.prepared import AiogramPreparedMessages, NoPreparedMessages
from app.platform.telegram.texts import BOT_DEFAULTS

log = structlog.get_logger(__name__)

ANALYTICS_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
AI_CONNECT_TIMEOUT = 5.0
ANTHROPIC_API = "https://api.anthropic.com"
"""Явно: иначе SDK берёт `ANTHROPIC_BASE_URL` из окружения, и ключ с текстами ушли бы туда."""
AI_MAX_RETRIES = 1
"""SDK Anthropic повторяет 429, 5xx и обрывы с паузой; вся проверка вместе с повтором всё равно
укладывается в AI_TIMEOUT_SECONDS (дедлайн адаптера)."""


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
    def metrics_settings(self, s: Settings) -> MetricsSettings:
        return s.metrics

    @provide(scope=Scope.APP)
    def healthchecks_settings(self, s: Settings) -> HealthchecksSettings:
        return s.healthchecks

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
    async def telegram_bot(
        self, settings: TelegramSettings, metrics: TelegramMetrics
    ) -> AsyncIterator[Bot]:
        """Клиент Bot API окружения: один на процесс, сессия закрывается при остановке."""
        # тексты бота — HTML (platform/telegram/texts.py): <b>, переносы; параметры экранированы
        bot = Bot(settings.bot_token.get_secret_value(), default=BOT_DEFAULTS)
        bot.session.middleware(FloodWaitMetrics(metrics))  # 429 любого вызова — в метрику (3.3)
        yield bot
        await bot.session.close()

    @provide(scope=Scope.APP)
    def metrics_registry(self) -> CollectorRegistry:
        """Реестр метрик процесса; наружу — `metrics_server` на METRICS_PORT (3.3)."""
        return make_registry()

    @provide(scope=Scope.APP)
    def queue_metrics(self, registry: CollectorRegistry) -> QueueMetrics:
        return make_queue_metrics(registry)

    @provide(scope=Scope.APP)
    def http_metrics(self, registry: CollectorRegistry) -> HttpMetrics:
        return HttpMetrics(registry)

    @provide(scope=Scope.APP)
    def telegram_metrics(self, registry: CollectorRegistry) -> TelegramMetrics:
        return TelegramMetrics(registry)

    @provide(scope=Scope.APP)
    def telegram_sender(
        self, bot: Bot, valkey: Redis, settings: TelegramSettings
    ) -> TelegramSender:
        """Уведомления бота: Bot API с лимитером в Valkey (25 msg/s, 1 msg/s на чат). Нагрузочный
        прогон stage (8.3) — фейк с тем же лимитером и латентностью Bot API, наружу ничего."""
        limiter = ValkeySendLimiter(valkey)
        if settings.fake_sender:
            log.warning("telegram_fake_sender", reason="TELEGRAM_FAKE_SENDER: nothing is sent")
            return FakeTelegramSender(limiter)
        return AiogramTelegramSender(bot, limiter)

    @provide(scope=Scope.APP)
    def prepared_messages(self, bot: Bot, app: AppSettings) -> PreparedMessages:
        """Карточки для shareMessage (7.4). В тестах Bot API не зовём: клиент делится ссылкой."""
        if app.env is Environment.TEST:
            return NoPreparedMessages()
        return AiogramPreparedMessages(bot)

    @provide(scope=Scope.APP)
    def storage(self, settings: S3Settings, clock: Clock) -> Iterator[StoragePort]:
        """S3/R2: клиенты boto3 создаются при первом запросе порта (без ключей — ошибка)."""
        storage = S3Storage(settings, clock)
        yield storage
        storage.close()

    @provide(scope=Scope.APP)
    async def analytics(
        self,
        settings: AnalyticsSettings,
        app: AppSettings,
        maker: async_sessionmaker[AsyncSession],
    ) -> AsyncIterator[Analytics]:
        """PostHog EU, если есть ключ (K32); без ключа — события в лог (dev, тесты). События
        удалённых аккаунтов не уходят ни туда, ни туда (2.12b)."""
        deleted = SqlDeletedUsers(maker)
        if settings.posthog_api_key is None:
            if app.env in {Environment.STAGE, Environment.PRODUCTION}:
                log.warning("analytics_disabled", reason="ANALYTICS_POSTHOG_API_KEY is not set")
            yield LoggingAnalytics(deleted=deleted)
            return
        async with httpx.AsyncClient(timeout=ANALYTICS_TIMEOUT) as client:
            yield PostHogAnalytics(
                client,
                api_key=settings.posthog_api_key,
                host=settings.posthog_host,
                environment=app.env.value,
                deleted=deleted,
            )

    @provide(scope=Scope.APP)
    async def person_deletion(
        self, settings: AnalyticsSettings, app: AppSettings
    ) -> AsyncIterator[PersonDeletion]:
        """Удаление персоны в PostHog по UserDeleted (2.12b): personal API key со scope
        `person:write` и id проекта (K32a) — только когда события в PostHog уходят (ключ проекта
        K32). Без них — no-op с предупреждением на каждое удаление, а на stage и prod ещё и при
        старте: события есть, удалять нечем."""
        key, project = settings.posthog_personal_api_key, settings.posthog_project_id
        if settings.posthog_api_key is None:
            yield NoPersonDeletion(capturing=False)  # события в PostHog не уходят — удалять нечего
            return
        if key is None or project is None:
            if app.env in {Environment.STAGE, Environment.PRODUCTION}:
                log.warning("analytics_person_deletion_disabled", reason=MISSING_KEYS)
            yield NoPersonDeletion(capturing=True)
            return
        async with client_for(settings.posthog_host, project, key.get_secret_value()) as client:
            yield PostHogPersons(client)

    @provide(scope=Scope.APP)
    async def moderation(self, settings: AiSettings, app: AppSettings) -> AsyncIterator[Moderation]:
        """OpenAI omni-moderation, если есть ключ (K25)."""
        if settings.openai_api_key is None:
            stub = _stubs_allowed(app, "AI_OPENAI_API_KEY")
            yield StubModeration() if stub else NoModeration()
            return
        timeout = httpx.Timeout(settings.timeout_seconds, connect=AI_CONNECT_TIMEOUT)
        async with httpx.AsyncClient(timeout=timeout) as client:
            yield OpenAiModeration(
                client,
                api_key=settings.openai_api_key.get_secret_value(),
                model=settings.moderation_model,
                text_breaker=CircuitBreaker(),
                image_breaker=CircuitBreaker(),
                deadline=settings.timeout_seconds,
            )

    @provide(scope=Scope.APP)
    async def policy_classifier(
        self, settings: AiSettings, app: AppSettings
    ) -> AsyncIterator[PolicyClassifier]:
        """Claude (ADR-0016: Haiku 4.5), если есть ключ (K26)."""
        if settings.anthropic_api_key is None:
            stub = _stubs_allowed(app, "AI_ANTHROPIC_API_KEY")
            yield StubPolicyClassifier() if stub else NoPolicyClassifier()
            return
        async with anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key.get_secret_value(),
            base_url=ANTHROPIC_API,
            timeout=anthropic.Timeout(settings.timeout_seconds, connect=AI_CONNECT_TIMEOUT),
            max_retries=AI_MAX_RETRIES,
        ) as client:
            yield AnthropicPolicyClassifier(
                client,
                model=settings.classifier_model,
                breaker=CircuitBreaker(),
                deadline=settings.timeout_seconds,
            )

    secondary_image = provide(NoSecondaryImage, scope=Scope.APP, provides=SecondaryImage)
    """Q20: второго проверяющего изображений пока нет — сработавшие решает модератор."""

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
    def json_cache(self, valkey: Redis) -> JsonCache:
        return ValkeyJsonCache(valkey)

    @provide(scope=Scope.APP)
    def session_denylist(self, valkey: Redis, settings: JwtSettings) -> SessionDenylist:
        return SessionDenylist(valkey, ttl=timedelta(seconds=settings.access_ttl_seconds))

    entitlements = provide(UnlimitedEntitlements, scope=Scope.APP, provides=Entitlements)
    """MVP: тарифов нет — «без ограничений» (ADR-0018); v1 — сервис entitlements."""

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
    audit_reader = provide(SqlAuditReader, scope=Scope.REQUEST, provides=AuditReader)
    idempotency = provide(SqlIdempotencyStore, scope=Scope.REQUEST, provides=IdempotencyStore)


def _stubs_allowed(app: AppSettings, variable: str) -> bool:
    """Без ключа AI: в dev и тестах — заглушка, на stage и проде — «проверка недоступна»:
    контент уходит в ручную очередь, а не публикуется без AI (ADR-0016)."""
    if app.env in {Environment.STAGE, Environment.PRODUCTION}:
        log.warning("ai_check_disabled", reason=f"{variable} is not set")
        return False
    return True
