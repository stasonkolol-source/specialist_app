"""Отменить сделку (POST /deals/{id}/cancel, S26; DEVELOPMENT_PLAN 6.1a): сторона с причиной.
DealCancelled возвращает заявку в «опубликована», а прежних кандидатов — в «просмотрен» (§7.9)."""

from dataclasses import dataclass

from app.modules.deals.application.ports import DealRepository
from app.modules.deals.domain.deal import DealCancelReason
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DealId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelDealCommand:
    actor_id: UserId
    deal_id: DealId
    reason: DealCancelReason


class CancelDeal:
    def __init__(self, uow: UnitOfWork, deals: DealRepository, clock: Clock) -> None:
        self._uow, self._deals, self._clock = uow, deals, clock

    async def __call__(self, cmd: CancelDealCommand) -> None:
        async with self._uow:
            deal = await self._deals.get_for_update(cmd.deal_id)
            deal.cancel(actor_id=cmd.actor_id, reason=cmd.reason, now=self._clock.now())
            await self._deals.save(deal)
