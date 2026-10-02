"""Фасад deals (ADR-0020 §6): команды — в транзакции вызывающего модуля."""

from app.modules.deals.api import AgreedDealIn
from app.modules.deals.application.ports import DealRepository
from app.modules.deals.domain.deal import Deal, DealPriceType, DealTerms
from app.modules.deals.errors import InvalidDealError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DealId, new_id


class DealsFacade:
    def __init__(self, uow: UnitOfWork, deals: DealRepository, clock: Clock) -> None:
        self._uow, self._deals, self._clock = uow, deals, clock

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
            ),
            now=self._clock.now(),
        )
        await self._deals.add(deal)
        return deal.id
