"""Отозвать спор (POST /deals/{id}/dispute/withdraw, S52; DEVELOPMENT_PLAN 6.1c): открывший,
пока модератор не решил, — сделка снова идёт, кейс модерации закрывается без решения
(DisputeWithdrawn). Не участник сделки — 404, вторая сторона — 409."""

from dataclasses import dataclass

from app.modules.deals.application.ports import DealRepository, DisputeRepository
from app.modules.deals.domain.dispute import DisputeId
from app.modules.deals.errors import DealNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DealId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class WithdrawDisputeCommand:
    actor_id: UserId
    deal_id: DealId


class WithdrawDispute:
    def __init__(
        self, uow: UnitOfWork, deals: DealRepository, disputes: DisputeRepository, clock: Clock
    ) -> None:
        self._uow, self._deals, self._disputes, self._clock = uow, deals, disputes, clock

    async def __call__(self, cmd: WithdrawDisputeCommand) -> DisputeId:
        async with self._uow:
            deal = await self._deals.get_for_update(cmd.deal_id)
            if deal.role_of(cmd.actor_id) is None:
                raise DealNotFoundError(deal_id=cmd.deal_id)
            dispute = await self._disputes.active_for_update(cmd.deal_id)
            dispute.withdraw(deal=deal, actor_id=cmd.actor_id, now=self._clock.now())
            await self._disputes.save(dispute)
            await self._deals.save(deal)
        return dispute.id
