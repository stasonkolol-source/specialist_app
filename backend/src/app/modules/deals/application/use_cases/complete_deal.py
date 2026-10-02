"""«Работа выполнена» (POST /deals/{id}/complete, S26; DEVELOPMENT_PLAN 6.1a): отметка стороны;
отметили обе — сделка завершена (DealCompleted: заявка завершена, уровень доверия)."""

from dataclasses import dataclass

from app.modules.deals.application.ports import DealRepository
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DealId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class CompleteDealCommand:
    actor_id: UserId
    deal_id: DealId


class CompleteDeal:
    def __init__(self, uow: UnitOfWork, deals: DealRepository, clock: Clock) -> None:
        self._uow, self._deals, self._clock = uow, deals, clock

    async def __call__(self, cmd: CompleteDealCommand) -> bool:
        """True — сделка завершена этой отметкой."""
        async with self._uow:
            deal = await self._deals.get_for_update(cmd.deal_id)
            completed = deal.complete(actor_id=cmd.actor_id, now=self._clock.now())
            await self._deals.save(deal)
        return completed
