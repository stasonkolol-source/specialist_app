"""Сколько специалистов покажет выдача (DEVELOPMENT_PLAN 4.4): «Показать N» в шторке S06.

Те же этапы, что у выдачи (`QueryStages`), и число — у первого непустого: иначе шторка
обещала бы одно, а страница показала другое. Считается до 1000: шторке больше не нужно.
Блокировки вошедшего (4.7) не в счёт — как и в выдаче.
"""

from dataclasses import dataclass, replace
from typing import Final

from app.modules.catalog.api import CatalogApi
from app.modules.search.application.dto import SpecialistFilters
from app.modules.search.application.ports import Blocklist, SpecialistSearch
from app.modules.search.application.stages import QueryStages
from app.modules.search.domain.query import QueryText
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.ids import UserId

COUNT_CAP: Final = 1000


@dataclass(frozen=True, slots=True, kw_only=True)
class CountSpecialistsCommand:
    filters: SpecialistFilters
    q: str | None = None
    viewer_id: UserId | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SpecialistCount:
    count: int
    capped: bool
    """Подходит больше, чем считали: «Показать 1000+»."""


class CountSpecialists:
    def __init__(
        self, search: SpecialistSearch, catalog: CatalogApi, blocks: Blocklist, clock: Clock
    ) -> None:
        self._search, self._stages, self._clock = search, QueryStages(catalog), clock
        self._blocks = blocks

    async def __call__(self, cmd: CountSpecialistsCommand) -> SpecialistCount:
        if cmd.filters.missing_point:
            raise DomainValidationError(field="lat", reason="point_required")
        filters = cmd.filters
        if cmd.viewer_id is not None:
            hidden = await self._blocks.blocked_ids(cmd.viewer_id)
            filters = replace(filters, hidden_users=tuple(hidden))
        now = self._clock.now()
        async for match, _ in self._stages(QueryText.parse(cmd.q)):
            found = await self._search.count(filters, match, now=now, cap=COUNT_CAP)
            if found:
                return SpecialistCount(count=found, capped=found >= COUNT_CAP)
        return SpecialistCount(count=0, capped=False)
