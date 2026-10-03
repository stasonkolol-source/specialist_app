"""Отклонить «Договорились» (POST /deals/{id}/decline, S53; кнопка «Отклонить» под `deal.proposed`;
DEVELOPMENT_PLAN 6.3b): предложение отменяется с причиной «не договорились». Сделку, которую уже
подтвердили, так не отменить — 409 (отмена идущей сделки — POST /deals/{id}/cancel)."""

from dataclasses import dataclass

from app.modules.deals.application.ports import DealRepository
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DealId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class DeclineDealCommand:
    actor_id: UserId
    deal_id: DealId


class DeclineDeal:
    def __init__(self, uow: UnitOfWork, deals: DealRepository, clock: Clock) -> None:
        self._uow, self._deals, self._clock = uow, deals, clock

    async def __call__(self, cmd: DeclineDealCommand) -> None:
        async with self._uow:
            deal = await self._deals.get_for_update(cmd.deal_id)
            deal.decline(actor_id=cmd.actor_id, now=self._clock.now())
            await self._deals.save(deal)
