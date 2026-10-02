"""Контракт модуля deals для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из deals только этот файл.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.modules.deals.errors import DealNotFoundError as DealNotFoundError
from app.modules.deals.errors import InvalidDealError as InvalidDealError
from app.platform.kernel.ids import CategoryId, DealId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class AgreedDealIn:
    """Клиент выбрал отклик (jobs, 6.1a): условия — из отклика, название — снимок заявки."""

    client_id: UserId
    performer_id: UserId
    profile_id: UUID | None
    job_id: UUID
    response_id: UUID
    title: str
    category_id: CategoryId
    price_type: str
    """Цена отклика: `fixed`, `from`, `hourly`, `negotiable`."""
    agreed_price: int | None
    """Пара; у договорной — None."""


class DealsApi(Protocol):
    async def create_agreed(self, data: AgreedDealIn) -> DealId:
        """Сделка `agreed` в транзакции вызывающего: нужен активный UoW (ADR-0020 §4)."""
        ...
