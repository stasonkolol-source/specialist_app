"""Контракт модуля deals для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из deals только этот файл.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.deals.errors import DealNotFoundError as DealNotFoundError
from app.modules.deals.errors import InvalidDealError as InvalidDealError
from app.platform.kernel.ids import CategoryId, DealId, UserId
from app.platform.kernel.pagination import Page, PageRequest


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
class ProposedDealIn:
    """«Договорились» в чате (переписка, 6.3b): условия задаёт нажавшая сторона, вторая
    подтверждает или отклоняет за 72 ч."""

    client_id: UserId
    performer_id: UserId
    proposed_by: UserId
    profile_id: UUID | None
    conversation_id: UUID
    title: str
    category_id: CategoryId | None = None
    price_type: str | None = None
    """Как у цены отклика: `fixed`, `from`, `hourly`, `negotiable`; None — цену не назвали."""
    agreed_price: int | None = None
    scheduled_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DealBrief:
    """Сделка для уведомлений сторонам (6.1b) и переписки (6.3b): название, статус, стороны и
    время."""

    id: DealId
    client_id: UserId
    performer_id: UserId
    title: str
    status: str
    """DealStatus: уведомление нужно, пока сделка в ожидаемом статусе."""
    origin: str
    scheduled_at: datetime | None
    price_type: str | None = None
    """Как у цены отклика: `fixed`, `from`, `hourly`, `negotiable`; None — цену не называли."""
    agreed_price: int | None = None
    """Пара."""


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
    proposal_expires_at: datetime | None = None
    """Предложение «Договорились» истечёт тогда (S53); у других статусов — None."""
    category_id: CategoryId | None = None
    """Категория заявки сделки: отзыв по ней считается в среднем категории (7.2)."""


class DealsApi(Protocol):
    async def create_agreed(self, data: AgreedDealIn) -> DealId:
        """Сделка `agreed` в транзакции вызывающего: нужен активный UoW (ADR-0020 §4)."""
        ...

    async def propose(self, data: ProposedDealIn) -> DealId:
        """Сделка `proposed` в транзакции вызывающего: нужен активный UoW. InvalidDealError —
        условия не проходят (пустое название, цена вне диапазона)."""
        ...

    async def deal_brief(self, deal_id: DealId) -> DealBrief | None:
        """Название, статус и стороны сделки; None — нет такой."""
        ...

    async def deal_briefs(self, deal_ids: Collection[DealId]) -> dict[DealId, DealBrief]:
        """Сделки пачкой (статус в списке диалогов S29); каких нет — нет и в ответе."""
        ...

    async def deal_for_response(self, response_id: UUID) -> DealBrief | None:
        """Сделка по отклику (одна на отклик); нет — None. Переписка открывает контакты после
        `agreed` (6.3a)."""
        ...

    async def deal_for(self, deal_id: DealId, viewer_id: UserId) -> DealSummary:
        """Сделка стороне; не участник или нет такой — DealNotFoundError (404)."""
        ...

    async def my_deals(self, viewer_id: UserId, page: PageRequest) -> Page[DealSummary]:
        """Свои сделки в обеих ролях, новые первыми (S28 «Сделки и отзывы», 7.3)."""
        ...
