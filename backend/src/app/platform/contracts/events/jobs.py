"""События модуля jobs (ADR-0020 §2; ARCHITECTURE §5.3, §7.9). Подписчики: модерация (через
ModerationRequested), уведомления, поиск заявок и подписки (5.3, 5.7), аналитика."""

from dataclasses import dataclass
from uuid import UUID

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import CategoryId, CityId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class JobSubmitted(DomainEvent):
    """Клиент создал заявку — она ждёт проверки."""

    event_type = "jobs.JobSubmitted"
    job_id: UUID
    client_id: UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class JobPublished(DomainEvent):
    """Заявка опубликована: после проверки или переопубликована после истечения."""

    event_type = "jobs.JobPublished"
    job_id: UUID
    client_id: UserId
    category_id: CategoryId
    city_id: CityId
    republished: bool = False
    """Не первая публикация: после правки, продления истёкшей — подписчикам не рассылать снова."""


@dataclass(frozen=True, slots=True, kw_only=True)
class JobUpdated(DomainEvent):
    """Клиент поправил или продлил заявку."""

    event_type = "jobs.JobUpdated"
    job_id: UUID
    client_id: UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class JobClosed(DomainEvent):
    """Заявка закрыта клиентом, снята модерацией или удалена (`reason` — CloseReason)."""

    event_type = "jobs.JobClosed"
    job_id: UUID
    client_id: UserId
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class JobExpired(DomainEvent):
    """Срок заявки вышел (`jobs.expire_jobs`)."""

    event_type = "jobs.JobExpired"
    job_id: UUID
    client_id: UserId
