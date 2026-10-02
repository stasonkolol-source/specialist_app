"""Сделка стороне (GET /deals/{id}, S26; DEVELOPMENT_PLAN 6.1a): не участник — 404."""

from dataclasses import dataclass

from app.modules.deals.application.dto import DealView
from app.modules.deals.application.ports import DealQueries
from app.modules.deals.errors import DealNotFoundError
from app.platform.kernel.ids import DealId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ShowDealCommand:
    actor_id: UserId
    deal_id: DealId


class ShowDeal:
    def __init__(self, queries: DealQueries) -> None:
        self._queries = queries

    async def __call__(self, cmd: ShowDealCommand) -> DealView:
        deal = await self._queries.view(cmd.deal_id)
        if deal is None or deal.role_of(cmd.actor_id) is None:
            raise DealNotFoundError(deal_id=cmd.deal_id)
        return deal
