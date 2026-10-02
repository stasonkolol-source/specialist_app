"""Свои сделки (GET /me/deals; DEVELOPMENT_PLAN 6.1a): клиентом, исполнителем или все, по
статусам, новые первыми."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.deals.application.dto import DealView
from app.modules.deals.application.ports import DealQueries
from app.modules.deals.domain.deal import DealRole, DealStatus
from app.platform.kernel.ids import UserId
from app.platform.kernel.pagination import Page, PageRequest


@dataclass(frozen=True, slots=True, kw_only=True)
class ListMyDealsCommand:
    actor_id: UserId
    role: DealRole | None
    statuses: Sequence[DealStatus]
    page: PageRequest


class ListMyDeals:
    def __init__(self, queries: DealQueries) -> None:
        self._queries = queries

    async def __call__(self, cmd: ListMyDealsCommand) -> Page[DealView]:
        return await self._queries.mine(
            cmd.actor_id, role=cmd.role, statuses=cmd.statuses, page=cmd.page
        )
