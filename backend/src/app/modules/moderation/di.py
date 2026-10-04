"""Сборка модуля moderation для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide
from prometheus_client import CollectorRegistry
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.identity.api import DeletionHold, IdentityApi
from app.modules.jobs.api import JobsApi
from app.modules.media.api import LegalHold, MediaModeration
from app.modules.messaging.api import MessagingApi
from app.modules.moderation.application.content_rules import ContentRulesChecker
from app.modules.moderation.application.policy import PublishedModerationPolicy
from app.modules.moderation.application.ports import (
    AutoCheckMetrics,
    CaseQueue,
    CaseRepository,
    CaseStats,
    ModerationPolicy,
    ModerationTargets,
    ModeratorsChat,
    RateLimitOverflows,
    ReportQuota,
    ReportRepository,
    ReportTargets,
    RiskSignals,
    RuleExamples,
    RuleSource,
    RuleWriter,
    SanctionRepository,
    VelocityCounter,
)
from app.modules.moderation.application.queries import ModerationQueries
from app.modules.moderation.application.use_cases.auto_check import AutoCheck
from app.modules.moderation.application.use_cases.check_duplicates import CheckDuplicates
from app.modules.moderation.application.use_cases.check_image import CheckImage
from app.modules.moderation.application.use_cases.create_report import CreateReport
from app.modules.moderation.application.use_cases.decide_case import CaseDecider, DecideCase
from app.modules.moderation.application.use_cases.file_appeal import FileAppeal
from app.modules.moderation.application.use_cases.import_content_rules import (
    ImportContentRules,
)
from app.modules.moderation.application.use_cases.inspect_dispute import InspectDispute
from app.modules.moderation.application.use_cases.open_case import CaseOpener, OpenCase
from app.modules.moderation.application.use_cases.post_case_card import PostCaseCard
from app.modules.moderation.application.use_cases.record_rate_limit_signals import (
    RecordRateLimitSignals,
)
from app.modules.moderation.application.use_cases.record_reregistration import (
    RecordReregistration,
)
from app.modules.moderation.application.use_cases.resolve_dispute import ResolveDispute
from app.modules.moderation.application.use_cases.take_case import EscalateCase, TakeCase
from app.modules.moderation.application.use_cases.track_dispute import TrackDispute
from app.modules.moderation.application.use_cases.try_content_rule import TryContentRule
from app.modules.moderation.domain.cases import EntityType
from app.modules.moderation.domain.rules import RegexEngine
from app.modules.moderation.infrastructure.cases import (
    SqlCaseRepository,
    SqlRiskSignals,
    SqlSanctionRepository,
)
from app.modules.moderation.infrastructure.chat import TelegramModeratorsChat
from app.modules.moderation.infrastructure.deletion_hold import CasesDeletionHold
from app.modules.moderation.infrastructure.legal_hold import CasesLegalHold
from app.modules.moderation.infrastructure.metrics import PrometheusAutoCheckMetrics
from app.modules.moderation.infrastructure.queries import SqlCaseQueue, SqlCaseStats
from app.modules.moderation.infrastructure.quota import ValkeyReportQuota
from app.modules.moderation.infrastructure.rate_limits import ValkeyRateLimitOverflows
from app.modules.moderation.infrastructure.regex import RE2
from app.modules.moderation.infrastructure.reports import FacadeReportTargets, SqlReportRepository
from app.modules.moderation.infrastructure.retention_hold import CasesRetentionHold
from app.modules.moderation.infrastructure.rule_examples import YamlRuleExamples
from app.modules.moderation.infrastructure.rules import CachedRuleSource, SqlRuleWriter
from app.modules.moderation.infrastructure.targets import TargetRegistry
from app.modules.moderation.infrastructure.targets.job import JobTarget
from app.modules.moderation.infrastructure.targets.media import MediaTarget
from app.modules.moderation.infrastructure.targets.message import MessageTarget
from app.modules.moderation.infrastructure.targets.portfolio import PortfolioTarget
from app.modules.moderation.infrastructure.targets.profile import ProfileTarget
from app.modules.moderation.infrastructure.targets.response import ResponseTarget
from app.modules.moderation.infrastructure.targets.review import ReviewReplyTarget, ReviewTarget
from app.modules.moderation.infrastructure.velocity import ValkeyVelocityCounter
from app.modules.reviews.api import ReviewsApi
from app.modules.specialists.api import SpecialistsApi
from app.platform.config.port import LegalVersions
from app.platform.db.port import UnitOfWork
from app.platform.i18n.translator import Translator
from app.platform.legal.port import LegalLibrary
from app.platform.privacy.port import RetentionHold
from app.platform.ratelimit import RateLimiter
from app.platform.settings import TelegramSettings
from app.platform.telegram.port import TelegramSender


class ModerationProvider(Provider):
    """Провайдер модуля moderation: связывает порты с реализациями."""

    scope = Scope.REQUEST

    rule_writer = provide(SqlRuleWriter, provides=RuleWriter)
    import_content_rules = provide(ImportContentRules)

    @provide(scope=Scope.APP)
    def regex_engine(self) -> RegexEngine:
        """Регулярки правил — RE2: линейное время при любом шаблоне (2.7b)."""
        return RE2

    @provide(scope=Scope.APP)
    def rule_source(
        self, maker: async_sessionmaker[AsyncSession], engine: RegexEngine
    ) -> RuleSource:
        """Снимок словаря — один на процесс, обновляется раз в TTL."""
        return CachedRuleSource(maker, engine=engine)

    try_content_rule = provide(TryContentRule)

    @provide(scope=Scope.APP)
    def rule_examples(self) -> RuleExamples:
        """Набор примеров seeds/moderation/rule_examples.yaml — из файла образа, раз на процесс."""
        return YamlRuleExamples()

    @provide(scope=Scope.APP)
    def velocity(self, valkey: Redis) -> VelocityCounter:
        return ValkeyVelocityCounter(valkey)

    @provide(scope=Scope.APP)
    def overflows(self, limiter: RateLimiter) -> RateLimitOverflows:
        return ValkeyRateLimitOverflows(limiter)

    @provide(scope=Scope.APP)
    def report_quota(self, limiter: RateLimiter) -> ReportQuota:
        return ValkeyReportQuota(limiter)

    @provide
    def report_targets(
        self,
        identity: IdentityApi,
        specialists: SpecialistsApi,
        jobs: JobsApi,
        reviews: ReviewsApi,
        messaging: MessagingApi,
    ) -> ReportTargets:
        """На кого жалоба (4.7): автор объекта — через фасады модулей-владельцев."""
        return FacadeReportTargets(identity, specialists, jobs, reviews, messaging)

    @provide(scope=Scope.APP)
    def policy(self, versions: LegalVersions, library: LegalLibrary) -> ModerationPolicy:
        return PublishedModerationPolicy(versions, library)

    @provide
    def targets(
        self,
        specialists: SpecialistsApi,
        jobs: JobsApi,
        messaging: MessagingApi,
        reviews: ReviewsApi,
        media: MediaModeration,
        uow: UnitOfWork,
    ) -> ModerationTargets:
        """Адаптеры целей: контентные модули добавляют свои в своих шагах."""
        return TargetRegistry(
            {
                EntityType.MEDIA: MediaTarget(media, specialists),
                EntityType.PORTFOLIO: PortfolioTarget(uow, specialists, media),
                EntityType.PROFILE: ProfileTarget(specialists),
                EntityType.JOB: JobTarget(jobs),
                EntityType.RESPONSE: ResponseTarget(jobs),
                EntityType.MESSAGE: MessageTarget(messaging),
                EntityType.REVIEW: ReviewTarget(reviews),
                EntityType.REVIEW_REPLY: ReviewReplyTarget(reviews),
            }
        )

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
    check_duplicates = provide(CheckDuplicates)
    check_image = provide(CheckImage)
    legal_hold = provide(CasesLegalHold, provides=LegalHold)
    deletion_hold = provide(CasesDeletionHold, provides=DeletionHold)
    retention_hold = provide(CasesRetentionHold, provides=RetentionHold)
    record_reregistration = provide(RecordReregistration)
    """media.purge_deleted не стирает доказательства открытых кейсов (ADR-0016 §6)."""
    queries = provide(ModerationQueries)
    open_case = provide(OpenCase)
    take_case = provide(TakeCase)
    escalate_case = provide(EscalateCase)
    decider = provide(CaseDecider)
    decide_case = provide(DecideCase)
    track_dispute = provide(TrackDispute)
    resolve_dispute = provide(ResolveDispute)
    inspect_dispute = provide(InspectDispute)
    record_rate_limit_signals = provide(RecordRateLimitSignals)
    reports = provide(SqlReportRepository, provides=ReportRepository)
    create_report = provide(CreateReport)
    file_appeal = provide(FileAppeal)
    post_case_card = provide(PostCaseCard)

    @provide(scope=Scope.APP)
    def moderators_chat(
        self, sender: TelegramSender, translator: Translator, telegram: TelegramSettings
    ) -> ModeratorsChat:
        """Чат модераторов (K29): пусто в настройках — карточек нет."""
        return TelegramModeratorsChat(sender, translator, telegram.moderators_chat_id)
