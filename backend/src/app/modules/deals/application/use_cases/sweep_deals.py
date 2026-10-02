"""Сроки сделок (периодические задачи `deals.*`, DEVELOPMENT_PLAN 6.1b, ARCHITECTURE §12.3):
напоминание за 2 ч до времени, «Работа выполнена?» после него, автозавершение через 72 ч после
отметки одной стороны, истечение предложения «Договорились». Каждая сделка — своей короткой
транзакцией: действие стороны ждёт одну строку, а не весь проход. За проход — не больше
`limit`, остальные — в следующий.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Final

from app.modules.deals.application.ports import DealQueries, DealRepository, DealSweep
from app.modules.deals.domain.deal import Deal
from app.modules.deals.errors import DealNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock

BATCH: Final = 500

ACTIONS: Final[Mapping[DealSweep, Callable[[Deal, datetime], bool]]] = MappingProxyType(
    {
        DealSweep.REMIND: lambda deal, now: deal.remind(now=now),
        DealSweep.PROMPT: lambda deal, now: deal.prompt_completion(now=now),
        DealSweep.AUTO_COMPLETE: lambda deal, now: deal.auto_complete(now=now),
        DealSweep.EXPIRE_PROPOSALS: lambda deal, now: deal.expire_proposal(now=now),
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class SweepDealsCommand:
    sweep: DealSweep
    limit: int = BATCH


class SweepDeals:
    def __init__(
        self, uow: UnitOfWork, deals: DealRepository, queries: DealQueries, clock: Clock
    ) -> None:
        self._uow, self._deals, self._queries, self._clock = uow, deals, queries, clock

    async def __call__(self, cmd: SweepDealsCommand) -> int:
        """Сколько сделок изменил проход."""
        now = self._clock.now()
        act = ACTIONS[cmd.sweep]
        changed = 0
        for deal_id in await self._queries.due(cmd.sweep, now, limit=cmd.limit):
            async with self._uow:
                try:
                    deal = await self._deals.get_for_update(deal_id)
                except DealNotFoundError:
                    continue
                if act(deal, now):  # сторона успела раньше — уже не пора
                    await self._deals.save(deal)
                    changed += 1
        return changed
