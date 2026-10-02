"""Сборка модуля search для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide
from prometheus_client import CollectorRegistry

from app.modules.search.application.ports import (
    Favorites,
    IndexMetrics,
    PendingProfiles,
    QueryLog,
    SpecialistIndex,
    SpecialistSearch,
)
from app.modules.search.application.projection import SpecialistProjection
from app.modules.search.application.use_cases.add_favorite import AddFavorite
from app.modules.search.application.use_cases.count_by_category import CountByCategory
from app.modules.search.application.use_cases.count_specialists import CountSpecialists
from app.modules.search.application.use_cases.flush_index import FlushIndex
from app.modules.search.application.use_cases.forget_favorites import ForgetFavorites
from app.modules.search.application.use_cases.list_favorites import ListFavorites
from app.modules.search.application.use_cases.mark_profiles import MarkProfiles
from app.modules.search.application.use_cases.reconcile_index import ReconcileIndex
from app.modules.search.application.use_cases.remove_favorite import RemoveFavorite
from app.modules.search.application.use_cases.report_zero_results import ReportZeroResults
from app.modules.search.application.use_cases.search_specialists import SearchSpecialists
from app.modules.search.application.use_cases.suggest_categories import SuggestCategories
from app.modules.search.infrastructure.favorites import SqlFavorites
from app.modules.search.infrastructure.index import SqlSpecialistIndex
from app.modules.search.infrastructure.metrics import PrometheusIndexMetrics
from app.modules.search.infrastructure.pending import SqlPendingProfiles
from app.modules.search.infrastructure.query_log import SqlQueryLog
from app.modules.search.infrastructure.search import SqlSpecialistSearch


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
    specialist_search = provide(SqlSpecialistSearch, provides=SpecialistSearch)
    query_log = provide(SqlQueryLog, provides=QueryLog)
    search_specialists = provide(SearchSpecialists)
    suggest_categories = provide(SuggestCategories)
    count_specialists = provide(CountSpecialists)
    count_by_category = provide(CountByCategory)
    favorites = provide(SqlFavorites, provides=Favorites)
    add_favorite = provide(AddFavorite)
    remove_favorite = provide(RemoveFavorite)
    list_favorites = provide(ListFavorites)
    forget_favorites = provide(ForgetFavorites)
    report_zero_results = provide(ReportZeroResults)
