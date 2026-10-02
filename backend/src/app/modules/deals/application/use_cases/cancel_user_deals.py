"""Аккаунт удалён (подписчик UserDeleted; DEVELOPMENT_PLAN 6.1a, ARCHITECTURE §7.10): его идущие
сделки и предложения «Договорились» отменяет система — заявка второй стороны снова открыта.
Сделка под спором остаётся до решения модератора (legal hold, 6.1c)."""

from dataclasses import dataclass

from app.modules.deals.application.ports import DealRepository
from app.modules.deals.domain.deal import DealCancelReason
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelUserDealsCommand:
    user_id: UserId


class CancelUserDeals:
    def __init__(self, uow: UnitOfWork, deals: DealRepository, clock: Clock) -> None:
        self._uow, self._deals, self._clock = uow, deals, clock

    async def __call__(self, cmd: CancelUserDealsCommand) -> int:
        """Сколько сделок отменено."""
        cancelled = 0
        async with self._uow:
            for deal_id in await self._deals.cancellable_of(cmd.user_id):
                deal = await self._deals.get_for_update(deal_id)
                if deal.cancel_by_system(
                    reason=DealCancelReason.ACCOUNT_DELETED, now=self._clock.now()
                ):
                    await self._deals.save(deal)
                    cancelled += 1
        return cancelled
