"""Сборка модуля geo для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.geo.api import GeoApi
from app.modules.geo.application.facade import GeoFacade
from app.modules.geo.application.ports import GeoQuery, GeoWriter
from app.modules.geo.application.use_cases.import_city import ImportCity
from app.modules.geo.infrastructure.queries import SqlGeoQuery
from app.modules.geo.infrastructure.writer import SqlGeoWriter


class GeoProvider(Provider):
    """Провайдер модуля geo: связывает порты с реализациями."""

    scope = Scope.REQUEST

    query = provide(SqlGeoQuery, provides=GeoQuery)
    writer = provide(SqlGeoWriter, provides=GeoWriter)
    facade = provide(GeoFacade, provides=GeoApi)
    import_city = provide(ImportCity)
