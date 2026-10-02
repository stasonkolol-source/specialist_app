"""Фасад deals (ADR-0020 §6): команды — в транзакции вызывающего модуля."""

from collections.abc import Collection
from uuid import UUID

from app.modules.deals.api import AgreedDealIn, DealBrief, ProposedDealIn
from app.modules.deals.application.dto import DealView
from app.modules.deals.application.ports import DealQueries, DealRepository
from app.modules.deals.domain.deal import Deal, DealPriceType, DealTerms
from app.modules.deals.errors import InvalidDealError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DealId, new_id


class DealsFacade:
    def __init__(
        self, uow: UnitOfWork, deals: DealRepository, queries: DealQueries, clock: Clock
    ) -> None:
        self._uow, self._deals, self._queries, self._clock = uow, deals, queries, clock

    async def deal_brief(self, deal_id: DealId) -> DealBrief | None:
        deal = await self._queries.view(deal_id)
        return _brief(deal) if deal is not None else None

    async def deal_briefs(self, deal_ids: Collection[DealId]) -> dict[DealId, DealBrief]:
        return {deal.id: _brief(deal) for deal in await self._queries.views(deal_ids)}

    async def deal_for_response(self, response_id: UUID) -> DealBrief | None:
        deal_id = await self._queries.of_response(response_id)
        return await self.deal_brief(deal_id) if deal_id is not None else None

    async def create_agreed(self, data: AgreedDealIn) -> DealId:
        self._uow.require_active()  # транзакция jobs: отклик выбран и сделка создана вместе
        price_type = _price_type(data.price_type)
        deal = Deal.agree_from_response(
            deal_id=DealId(new_id()),
            client_id=data.client_id,
            performer_id=data.performer_id,
            profile_id=data.profile_id,
            job_id=data.job_id,
            response_id=data.response_id,
            terms=DealTerms(
                title=data.title,
                category_id=data.category_id,
                price_type=price_type,
                agreed_price=data.agreed_price,
                scheduled_at=data.scheduled_at,
            ),
            now=self._clock.now(),
        )
        await self._deals.add(deal)
        return deal.id

    async def propose(self, data: ProposedDealIn) -> DealId:
        self._uow.require_active()  # транзакция переписки: сделка и сообщение о ней вместе
        deal = Deal.propose(
            deal_id=DealId(new_id()),
            client_id=data.client_id,
            performer_id=data.performer_id,
            proposed_by=data.proposed_by,
            profile_id=data.profile_id,
            conversation_id=data.conversation_id,
            terms=DealTerms(
                title=data.title,
                category_id=data.category_id,
                price_type=_price_type(data.price_type) if data.price_type else None,
                agreed_price=data.agreed_price,
                scheduled_at=data.scheduled_at,
            ),
            now=self._clock.now(),
        )
        await self._deals.add(deal)
        return deal.id


def _price_type(value: str) -> DealPriceType:
    try:
        return DealPriceType(value)
    except ValueError:
        raise InvalidDealError(field="price_type", reason="unknown") from None


def _brief(deal: DealView) -> DealBrief:
    return DealBrief(
        id=deal.id,
        client_id=deal.client_id,
        performer_id=deal.performer_id,
        title=deal.title,
        status=deal.status.value,
        origin=deal.origin.value,
        scheduled_at=deal.scheduled_at,
        price_type=deal.price_type.value if deal.price_type is not None else None,
        agreed_price=deal.agreed_price,
    )
