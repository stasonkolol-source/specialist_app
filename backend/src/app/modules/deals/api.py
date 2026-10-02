"""Контракт модуля deals для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из deals только этот файл.
"""

from dataclasses import dataclass
from datetime import datetime
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
    scheduled_at: datetime | None = None
    """Время работы, если заявка его называет (окно «Сегодня 18–21», дата и время): по нему —
    напоминание и «Работа выполнена?» (6.1b)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DealBrief:
    """Сделка для уведомлений сторонам (6.1b): название, статус, стороны и время."""

    client_id: UserId
    performer_id: UserId
    title: str
    status: str
    """DealStatus: уведомление нужно, пока сделка в ожидаемом статусе."""
    origin: str
    scheduled_at: datetime | None


@dataclass(frozen=True, slots=True, kw_only=True)
class DealSummary:
    """Сделка стороне — экран сделки S26 (6.2): условия, стороны и вехи. Значения перечислений —
    строками: `status` (DealStatus), `origin`, `my_role` (`client` | `performer`), цена — пара."""

    id: DealId
    status: str
    origin: str
    my_role: str
    title: str
    price_type: str | None
    agreed_price: int | None
    scheduled_at: datetime | None
    client_id: UserId
    performer_id: UserId
    profile_id: UUID | None
    job_id: UUID | None
    response_id: UUID | None
    conversation_id: UUID | None
    proposed_by: UserId | None
    agreed_at: datetime | None
    client_confirmed_at: datetime | None
    performer_confirmed_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancelled_by: UserId | None
    cancel_reason: str | None
    created_at: datetime
    version: int


class DealsApi(Protocol):
    async def create_agreed(self, data: AgreedDealIn) -> DealId:
        """Сделка `agreed` в транзакции вызывающего: нужен активный UoW (ADR-0020 §4)."""
        ...

    async def deal_brief(self, deal_id: DealId) -> DealBrief | None:
        """Название, статус и стороны сделки; None — нет такой."""
        ...

    async def deal_for(self, deal_id: DealId, viewer_id: UserId) -> DealSummary:
        """Сделка стороне; не участник или нет такой — DealNotFoundError (404)."""
        ...
