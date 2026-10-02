"""Фасад deals (ADR-0020 §6): команды — в транзакции вызывающего модуля."""

from app.modules.deals.api import AgreedDealIn, DealBrief, DealSummary
from app.modules.deals.application.ports import DealQueries, DealRepository
from app.modules.deals.domain.deal import Deal, DealPriceType, DealTerms
from app.modules.deals.errors import DealNotFoundError, InvalidDealError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DealId, UserId, new_id


class DealsFacade:
    def __init__(
        self, uow: UnitOfWork, deals: DealRepository, queries: DealQueries, clock: Clock
    ) -> None:
        self._uow, self._deals, self._queries, self._clock = uow, deals, queries, clock

    async def deal_brief(self, deal_id: DealId) -> DealBrief | None:
        deal = await self._queries.view(deal_id)
        if deal is None:
            return None
        return DealBrief(
            client_id=deal.client_id,
            performer_id=deal.performer_id,
            title=deal.title,
            status=deal.status.value,
            origin=deal.origin.value,
            scheduled_at=deal.scheduled_at,
        )

    async def deal_for(self, deal_id: DealId, viewer_id: UserId) -> DealSummary:
        deal = await self._queries.view(deal_id)
        role = deal.role_of(viewer_id) if deal is not None else None
        if deal is None or role is None:
            raise DealNotFoundError(deal_id=deal_id)
        return DealSummary(
            id=deal.id,
            status=deal.status.value,
            origin=deal.origin.value,
            my_role=role.value,
            title=deal.title,
            price_type=deal.price_type.value if deal.price_type is not None else None,
            agreed_price=deal.agreed_price,
            scheduled_at=deal.scheduled_at,
            client_id=deal.client_id,
            performer_id=deal.performer_id,
            profile_id=deal.profile_id,
            job_id=deal.job_id,
            response_id=deal.response_id,
            conversation_id=deal.conversation_id,
            proposed_by=deal.proposed_by,
            agreed_at=deal.agreed_at,
            client_confirmed_at=deal.client_confirmed_at,
            performer_confirmed_at=deal.performer_confirmed_at,
            completed_at=deal.completed_at,
            cancelled_at=deal.cancelled_at,
            cancelled_by=deal.cancelled_by,
            cancel_reason=deal.cancel_reason.value if deal.cancel_reason is not None else None,
            created_at=deal.created_at,
            version=deal.version,
        )

    async def create_agreed(self, data: AgreedDealIn) -> DealId:
        self._uow.require_active()  # транзакция jobs: отклик выбран и сделка создана вместе
        try:
            price_type = DealPriceType(data.price_type)
        except ValueError:
            raise InvalidDealError(field="price_type", reason="unknown") from None
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
