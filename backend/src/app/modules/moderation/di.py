"""Сборка модуля moderation для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide
from prometheus_client import CollectorRegistry
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.media.api import LegalHold
from app.modules.moderation.application.content_rules import ContentRulesChecker
from app.modules.moderation.application.policy import PublishedModerationPolicy
from app.modules.moderation.application.ports import (
    AutoCheckMetrics,
    CaseQueue,
    CaseRepository,
    CaseStats,
    ModerationPolicy,
    ModerationTargets,
    RateLimitOverflows,
    RiskSignals,
    RuleSource,
    RuleWriter,
    SanctionRepository,
    VelocityCounter,
)
from app.modules.moderation.application.queries import ModerationQueries
from app.modules.moderation.application.use_cases.auto_check import AutoCheck
from app.modules.moderation.application.use_cases.decide_case import DecideCase
from app.modules.moderation.application.use_cases.import_content_rules import (
    ImportContentRules,
)
from app.modules.moderation.application.use_cases.open_case import CaseOpener, OpenCase
from app.modules.moderation.application.use_cases.record_rate_limit_signals import (
    RecordRateLimitSignals,
)
from app.modules.moderation.application.use_cases.take_case import EscalateCase, TakeCase
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.infrastructure.cases import (
    SqlCaseRepository,
    SqlRiskSignals,
    SqlSanctionRepository,
)
from app.modules.moderation.infrastructure.legal_hold import CasesLegalHold
from app.modules.moderation.infrastructure.metrics import PrometheusAutoCheckMetrics
from app.modules.moderation.infrastructure.queries import SqlCaseQueue, SqlCaseStats
from app.modules.moderation.infrastructure.rate_limits import ValkeyRateLimitOverflows
from app.modules.moderation.infrastructure.rules import CachedRuleSource, SqlRuleWriter
from app.modules.moderation.infrastructure.targets import TargetRegistry
from app.modules.moderation.infrastructure.targets.profile import ProfileTarget
from app.modules.moderation.infrastructure.velocity import ValkeyVelocityCounter
from app.modules.specialists.api import SpecialistsApi
from app.platform.config.port import LegalVersions
from app.platform.legal.port import LegalLibrary
from app.platform.ratelimit import RateLimiter


class ModerationProvider(Provider):
    """Провайдер модуля moderation: связывает порты с реализациями."""

    scope = Scope.REQUEST

    rule_writer = provide(SqlRuleWriter, provides=RuleWriter)
    import_content_rules = provide(ImportContentRules)

    @provide(scope=Scope.APP)
    def rule_source(self, maker: async_sessionmaker[AsyncSession]) -> RuleSource:
        """Снимок словаря — один на процесс, обновляется раз в TTL."""
        return CachedRuleSource(maker)

    @provide(scope=Scope.APP)
    def velocity(self, valkey: Redis) -> VelocityCounter:
        return ValkeyVelocityCounter(valkey)

    @provide(scope=Scope.APP)
    def overflows(self, limiter: RateLimiter) -> RateLimitOverflows:
        return ValkeyRateLimitOverflows(limiter)

    @provide(scope=Scope.APP)
    def policy(self, versions: LegalVersions, library: LegalLibrary) -> ModerationPolicy:
        return PublishedModerationPolicy(versions, library)

    @provide
    def targets(self, specialists: SpecialistsApi) -> ModerationTargets:
        """Адаптеры целей: контентные модули добавляют свои в своих шагах (5.1, 5.4, …)."""
        return TargetRegistry({EntityType.PROFILE: ProfileTarget(specialists)})

    @provide(scope=Scope.APP)
    def auto_check_metrics(self, registry: CollectorRegistry) -> AutoCheckMetrics:
        return PrometheusAutoCheckMetrics(registry)

    checker = provide(ContentRulesChecker, scope=Scope.APP)

    cases = provide(SqlCaseRepository, provides=CaseRepository)
    sanctions = provide(SqlSanctionRepository, provides=SanctionRepository)
    signals = provide(SqlRiskSignals, provides=RiskSignals)
    stats = provide(SqlCaseStats, provides=CaseStats)
    case_queue = provide(SqlCaseQueue, provides=CaseQueue)
    opener = provide(CaseOpener)
    auto_check = provide(AutoCheck)
    legal_hold = provide(CasesLegalHold, provides=LegalHold)
    """media.purge_deleted не стирает доказательства открытых кейсов (ADR-0016 §6)."""
    queries = provide(ModerationQueries)
    open_case = provide(OpenCase)
    take_case = provide(TakeCase)
    escalate_case = provide(EscalateCase)
    decide_case = provide(DecideCase)
    record_rate_limit_signals = provide(RecordRateLimitSignals)
