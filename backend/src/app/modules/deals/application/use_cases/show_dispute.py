"""Спор стороне после действия (S52; DEVELOPMENT_PLAN 6.1c): спор и статус сделки. Не участник —
404."""

from dataclasses import dataclass

from app.modules.deals.application.dto import DisputeView
from app.modules.deals.application.ports import DealQueries, DisputeQueries
from app.modules.deals.domain.deal import DealStatus
from app.modules.deals.domain.dispute import DisputeId
from app.modules.deals.errors import DisputeNotFoundError
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ShowDisputeCommand:
    actor_id: UserId
    dispute_id: DisputeId


class ShowDispute:
    def __init__(self, deals: DealQueries, disputes: DisputeQueries) -> None:
        self._deals, self._disputes = deals, disputes

    async def __call__(self, cmd: ShowDisputeCommand) -> tuple[DisputeView, DealStatus]:
        dispute = await self._disputes.view(cmd.dispute_id)
        deal = await self._deals.view(dispute.deal_id) if dispute is not None else None
        if dispute is None or deal is None or deal.role_of(cmd.actor_id) is None:
            raise DisputeNotFoundError(dispute_id=cmd.dispute_id)
        return dispute, deal.status
