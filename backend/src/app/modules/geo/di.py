"""Сборка модуля geo для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.geo.api import GeoApi
from app.modules.geo.application.facade import GeoFacade
from app.modules.geo.application.ports import DirectoryCache, GeoQuery, GeoWriter
from app.modules.geo.application.use_cases.import_city import ImportCity
from app.modules.geo.infrastructure.cache import CachedGeoQuery, GeoDirectoryCache
from app.modules.geo.infrastructure.queries import SqlGeoQuery
from app.modules.geo.infrastructure.writer import SqlGeoWriter


class GeoProvider(Provider):
    """Провайдер модуля geo: связывает порты с реализациями."""

    scope = Scope.REQUEST

    @provide(scope=Scope.APP)
    def directory(self, maker: async_sessionmaker[AsyncSession]) -> GeoDirectoryCache:
        """Снимок справочника — один на процесс."""
        return GeoDirectoryCache(maker)

    @provide(scope=Scope.APP)
    def directory_cache(self, cache: GeoDirectoryCache) -> DirectoryCache:
        return cache

    sql = provide(SqlGeoQuery)
    query = provide(CachedGeoQuery, provides=GeoQuery)
    writer = provide(SqlGeoWriter, provides=GeoWriter)
    facade = provide(GeoFacade, provides=GeoApi)
    import_city = provide(ImportCity)
