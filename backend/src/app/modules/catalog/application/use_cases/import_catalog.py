"""Импорт таксономии из сидов (DEVELOPMENT_PLAN 1.3b, `cli seed`)."""

from dataclasses import dataclass

from app.modules.catalog.application.dto import CategorySeed, ImportResult
from app.modules.catalog.application.ports import CatalogWriter
from app.platform.contracts.events.catalog import CatalogChanged
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportCatalogCommand:
    categories: tuple[CategorySeed, ...]
    """Корни дерева с потомками."""


class ImportCatalog:
    def __init__(self, uow: UnitOfWork, writer: CatalogWriter, clock: Clock) -> None:
        self._uow, self._writer, self._clock = uow, writer, clock

    async def __call__(self, cmd: ImportCatalogCommand) -> ImportResult:
        async with self._uow:
            result = await self._writer.import_taxonomy(cmd.categories)
            if result.changed:
                self._uow.add_event(
                    CatalogChanged(category_ids=result.changed, occurred_at=self._clock.now())
                )
        return result
