"""Сборка модуля moderation для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.moderation.application.content_rules import ContentRulesChecker
from app.modules.moderation.application.ports import RuleSource, RuleWriter, VelocityCounter
from app.modules.moderation.application.use_cases.import_content_rules import (
    ImportContentRules,
)
from app.modules.moderation.infrastructure.rules import CachedRuleSource, SqlRuleWriter
from app.modules.moderation.infrastructure.velocity import ValkeyVelocityCounter


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

    checker = provide(ContentRulesChecker, scope=Scope.APP)
