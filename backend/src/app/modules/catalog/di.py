"""Сборка модуля catalog для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.catalog.api import CatalogApi
from app.modules.catalog.application.facade import CatalogFacade
from app.modules.catalog.application.ports import CatalogQuery, CatalogWriter, TaxonomyCache
from app.modules.catalog.application.use_cases.import_catalog import ImportCatalog
from app.modules.catalog.infrastructure.cache import CachedCatalogQuery, TaxonomySnapshotCache
from app.modules.catalog.infrastructure.queries import SqlCatalogQuery
from app.modules.catalog.infrastructure.writer import SqlCatalogWriter


class CatalogProvider(Provider):
    """Провайдер модуля catalog: связывает порты с реализациями."""

    scope = Scope.REQUEST

    @provide(scope=Scope.APP)
    def taxonomy(self, maker: async_sessionmaker[AsyncSession]) -> TaxonomySnapshotCache:
        """Снимок дерева — один на процесс."""
        return TaxonomySnapshotCache(maker)

    @provide(scope=Scope.APP)
    def taxonomy_cache(self, cache: TaxonomySnapshotCache) -> TaxonomyCache:
        return cache

    sql = provide(SqlCatalogQuery)
    query = provide(CachedCatalogQuery, provides=CatalogQuery)
    writer = provide(SqlCatalogWriter, provides=CatalogWriter)
    facade = provide(CatalogFacade, provides=CatalogApi)
    import_catalog = provide(ImportCatalog)
