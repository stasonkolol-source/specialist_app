"""Сборка модуля catalog для dishka (ADR-0020 §7)."""

from dishka import Provider, Scope, provide

from app.modules.catalog.api import CatalogApi
from app.modules.catalog.application.facade import CatalogFacade
from app.modules.catalog.application.ports import CatalogQuery, CatalogWriter
from app.modules.catalog.application.use_cases.import_catalog import ImportCatalog
from app.modules.catalog.infrastructure.queries import SqlCatalogQuery
from app.modules.catalog.infrastructure.writer import SqlCatalogWriter


class CatalogProvider(Provider):
    """Провайдер модуля catalog: связывает порты с реализациями."""

    scope = Scope.REQUEST

    query = provide(SqlCatalogQuery, provides=CatalogQuery)
    writer = provide(SqlCatalogWriter, provides=CatalogWriter)
    facade = provide(CatalogFacade, provides=CatalogApi)
    import_catalog = provide(ImportCatalog)
