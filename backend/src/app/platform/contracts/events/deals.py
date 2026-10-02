"""События модуля deals (ADR-0020 §2; ARCHITECTURE §7.9; DEVELOPMENT_PLAN 6.1a). Подписчики:
jobs (заявка «в работе», отменённая — снова открыта, завершённая — завершена), identity
(уровень доверия по завершённым сделкам), уведомления (6.1b), аналитика."""

from dataclasses import dataclass
from uuid import UUID

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import CategoryId, DealId, UserId


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
