"""Сборка модуля search для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide
from prometheus_client import CollectorRegistry

from app.modules.search.application.ports import IndexMetrics, PendingProfiles, SpecialistIndex
from app.modules.search.application.projection import SpecialistProjection
from app.modules.search.application.use_cases.flush_index import FlushIndex
from app.modules.search.application.use_cases.mark_profiles import MarkProfiles
from app.modules.search.application.use_cases.reconcile_index import ReconcileIndex
from app.modules.search.infrastructure.index import SqlSpecialistIndex
from app.modules.search.infrastructure.metrics import PrometheusIndexMetrics
from app.modules.search.infrastructure.pending import SqlPendingProfiles


class SearchProvider(Provider):
    """Провайдер модуля search: связывает порты с реализациями."""

    scope = Scope.REQUEST

    @provide(scope=Scope.APP)
    def index_metrics(self, registry: CollectorRegistry) -> IndexMetrics:
        return PrometheusIndexMetrics(registry)

    index = provide(SqlSpecialistIndex, provides=SpecialistIndex)
    pending = provide(SqlPendingProfiles, provides=PendingProfiles)
    projection = provide(SpecialistProjection)
    mark_profiles = provide(MarkProfiles)
    flush_index = provide(FlushIndex)
    reconcile_index = provide(ReconcileIndex)
