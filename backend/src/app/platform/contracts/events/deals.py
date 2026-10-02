"""События модуля deals (ADR-0020 §2; ARCHITECTURE §7.9; DEVELOPMENT_PLAN 6.1a). Подписчики:
jobs (заявка «в работе», отменённая — снова открыта, завершённая — завершена), identity
(уровень доверия по завершённым сделкам), уведомления (6.1b, 6.3b), переписка (6.3b),
аналитика."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import CategoryId, DealId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class DealProposed(DomainEvent):
    """«Договорились» в чате одной стороной (6.3b): вторая подтверждает или отклоняет за 72 ч."""

    event_type = "deals.DealProposed"
    deal_id: DealId
    client_id: UserId
    performer_id: UserId
    proposed_by: UserId
    conversation_id: UUID | None


@dataclass(frozen=True, slots=True, kw_only=True)
class DealAgreed(DomainEvent):
    """Стороны договорились: клиент выбрал отклик или вторая сторона подтвердила «Договорились»."""

    event_type = "deals.DealAgreed"
    deal_id: DealId
    client_id: UserId
    performer_id: UserId
    origin: str
    """DealOrigin: `job_response`, `direct`, `chat`."""
    job_id: UUID | None
    response_id: UUID | None
    category_id: CategoryId | None


@dataclass(frozen=True, slots=True, kw_only=True)
class DealCompleted(DomainEvent):
    """Работа выполнена: обе стороны подтвердили (или одна и 72 ч без возражений, 6.1b)."""

    event_type = "deals.DealCompleted"
    deal_id: DealId
    client_id: UserId
    performer_id: UserId
    origin: str
    job_id: UUID | None
    response_id: UUID | None
    category_id: CategoryId | None
    auto: bool = False
    """Завершила система: одна сторона отметила «выполнено», вторая молчала 72 ч (6.1b)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DealReminderDue(DomainEvent):
    """До времени сделки 2 ч: сторонам — напоминание `deal.reminder` (6.1b)."""

    event_type = "deals.DealReminderDue"
    deal_id: DealId
    client_id: UserId
    performer_id: UserId
    scheduled_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class DealCompletionDue(DomainEvent):
    """Время сделки прошло: «Работа выполнена?» `deal.completion_prompt` тем, кто ещё не
    отметил (6.1b)."""

    event_type = "deals.DealCompletionDue"
    deal_id: DealId
    client_id: UserId
    performer_id: UserId
    ask_client: bool
    ask_performer: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class DealCancelled(DomainEvent):
    """Сделку отменили: сторона с причиной, система (истекло предложение, удалён аккаунт) или
    модератор по спору (6.1c)."""

    event_type = "deals.DealCancelled"
    deal_id: DealId
    client_id: UserId
    performer_id: UserId
    origin: str
    job_id: UUID | None
    response_id: UUID | None
    category_id: CategoryId | None
    cancelled_by: str
    """DealRole отменившей стороны (`client`, `performer`) или `system`: от этого зависит, кем
    становится выбранный отклик — «отклонён» клиентом или «отозван» исполнителем (§7.9)."""
    reason: str
