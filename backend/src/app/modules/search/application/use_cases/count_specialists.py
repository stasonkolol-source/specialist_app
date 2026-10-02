"""Сколько специалистов покажет выдача (DEVELOPMENT_PLAN 4.4): «Показать N» в шторке S06.

Те же этапы, что у выдачи (`QueryStages`), и число — у первого непустого: иначе шторка
обещала бы одно, а страница показала другое. Считается до 1000: шторке больше не нужно.
"""

from dataclasses import dataclass
from typing import Final

from app.modules.catalog.api import CatalogApi
from app.modules.search.application.dto import SpecialistFilters
from app.modules.search.application.ports import SpecialistSearch
from app.modules.search.application.stages import QueryStages
from app.modules.search.domain.query import QueryText
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import DomainValidationError

COUNT_CAP: Final = 1000


@dataclass(frozen=True, slots=True, kw_only=True)
class CountSpecialistsCommand:
    filters: SpecialistFilters
    q: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SpecialistCount:
    count: int
    capped: bool
    """Подходит больше, чем считали: «Показать 1000+»."""


class CountSpecialists:
    def __init__(self, search: SpecialistSearch, catalog: CatalogApi, clock: Clock) -> None:
        self._search, self._stages, self._clock = search, QueryStages(catalog), clock

    async def __call__(self, cmd: CountSpecialistsCommand) -> SpecialistCount:
        if cmd.filters.missing_point:
            raise DomainValidationError(field="lat", reason="point_required")
        now = self._clock.now()
        async for match, _ in self._stages(QueryText.parse(cmd.q)):
            found = await self._search.count(cmd.filters, match, now=now, cap=COUNT_CAP)
            if found:
                return SpecialistCount(count=found, capped=found >= COUNT_CAP)
        return SpecialistCount(count=0, capped=False)
