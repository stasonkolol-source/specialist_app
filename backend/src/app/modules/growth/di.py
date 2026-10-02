"""Сборка модуля growth для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.growth.application.ports import AttributionRepository
from app.modules.growth.application.use_cases.forget_attribution import ForgetAttribution
from app.modules.growth.application.use_cases.record_attribution import RecordAttribution
from app.modules.growth.infrastructure.repositories import SqlAttributionRepository


class GrowthProvider(Provider):
    """Провайдер модуля growth: связывает порты с реализациями."""

    scope = Scope.REQUEST

    attributions = provide(SqlAttributionRepository, provides=AttributionRepository)
    record_attribution = provide(RecordAttribution)
    forget_attribution = provide(ForgetAttribution)
