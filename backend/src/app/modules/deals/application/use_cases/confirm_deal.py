"""Подтвердить «Договорились» (POST /deals/{id}/confirm; DEVELOPMENT_PLAN 6.1a, 6.4): вторая
сторона переводит предложение из чата в `agreed`."""

from dataclasses import dataclass

from app.modules.deals.application.ports import DealRepository
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DealId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ConfirmDealCommand:
    actor_id: UserId
    deal_id: DealId


class ConfirmDeal:
    def __init__(self, uow: UnitOfWork, deals: DealRepository, clock: Clock) -> None:
        self._uow, self._deals, self._clock = uow, deals, clock

    async def __call__(self, cmd: ConfirmDealCommand) -> None:
        async with self._uow:
            deal = await self._deals.get_for_update(cmd.deal_id)
            deal.confirm(actor_id=cmd.actor_id, now=self._clock.now())
            await self._deals.save(deal)
