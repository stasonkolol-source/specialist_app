"""События модуля jobs (ADR-0020 §2; ARCHITECTURE §5.3, §7.9). Подписчики: модерация (через
ModerationRequested), уведомления, поиск заявок и подписки (5.3, 5.7), аналитика. Отклики
(5.4) — события того же модуля: отклик — подагрегат заявки."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import CategoryId, CityId, DealId, UserId


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
    urgency: str
    """Urgency заявки: срез аналитики и режим рассылки подписчикам (5.7)."""
    republished: bool = False
    """Не первая публикация: после правки, продления истёкшей — подписчикам не рассылать снова."""
    direct: bool = False
    """Прямой запрос (`visibility = direct`, 5.6): её видят только приглашённые — подписчикам не
    рассылать, приглашённым — уведомление."""
    reviewed: bool = False
    """Опубликовал модератор после ручной проверки, а не автопроверка: клиенту — «Заявка
    опубликована» (после автопроверки он видит публикацию сразу на S21)."""


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
    category_id: CategoryId
    city_id: CityId
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class JobExpired(DomainEvent):
    """Срок заявки вышел (`jobs.expire_jobs`)."""

    event_type = "jobs.JobExpired"
    job_id: UUID
    client_id: UserId
    category_id: CategoryId
    city_id: CityId


@dataclass(frozen=True, slots=True, kw_only=True)
class JobExpiring(DomainEvent):
    """До конца срока опубликованной заявки осталось два часа (`jobs.expiry_reminders`):
    клиенту — «Продлить» или «Закрыть»."""

    event_type = "jobs.JobExpiring"
    job_id: UUID
    client_id: UserId
    expires_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseSubmitted(DomainEvent):
    """Исполнитель откликнулся: клиенту — уведомление (с дебаунсом), тексту — проверка."""

    event_type = "jobs.ResponseSubmitted"
    job_id: UUID
    response_id: UUID
    performer_id: UserId
    client_id: UserId
    is_first: bool
    """Первый отклик на заявку — «Откликнулся первым» и время до первого отклика (TTFR)."""
    published_at: datetime | None
    """Когда заявку опубликовали: время от публикации до отклика — в аналитику."""
    category_id: CategoryId | None = None
    city_id: CityId | None = None
    """Услуга и город заявки, как в JobPublished: метрики откликов в аналитике — по паре «город ×
    категория» (6.6). None — у события, поставленного в очередь до этих полей."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseUpdated(DomainEvent):
    """Исполнитель поправил отклик: новый текст снова проходит проверку."""

    event_type = "jobs.ResponseUpdated"
    job_id: UUID
    response_id: UUID
    performer_id: UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseWithdrawn(DomainEvent):
    """Исполнитель отозвал отклик (или его аккаунт удалён): место на заявке освободилось."""

    event_type = "jobs.ResponseWithdrawn"
    job_id: UUID
    response_id: UUID
    performer_id: UserId
    client_id: UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseAccepted(DomainEvent):
    """Клиент выбрал отклик исполнителем (6.1a): создана сделка `agreed`, остальные активные
    отклики — «не выбран», заявка — «в работе»."""

    event_type = "jobs.ResponseAccepted"
    job_id: UUID
    response_id: UUID
    performer_id: UserId
    client_id: UserId
    deal_id: DealId


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseDeclined(DomainEvent):
    """Клиент отклонил отклик (6.1a): место на заявке освободилось."""

    event_type = "jobs.ResponseDeclined"
    job_id: UUID
    response_id: UUID
    performer_id: UserId
    client_id: UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class JobInvited(DomainEvent):
    """Клиент пригласил специалиста в опубликованную заявку или его прямой запрос опубликован
    (5.6): специалисту — уведомление `job.invited` с «Посмотреть заявку» и «Откликнуться шаблоном»,
    в аналитику — `invite_sent` или `direct_request_sent`."""

    event_type = "jobs.JobInvited"
    job_id: UUID
    client_id: UserId
    profile_id: UUID
    performer_id: UserId
    """Владелец профиля — получатель уведомления."""
    direct: bool
    """Прямой запрос: заявку видит только он."""


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertCreated(DomainEvent):
    """Исполнитель подписался на новые заявки (S19, 5.7): в аналитику — `alert_created`."""

    event_type = "jobs.AlertCreated"
    alert_id: UUID
    user_id: UserId
    city_id: CityId
    delivery: str
    """`instant` или `digest`."""
    area: str
    """`city` (весь город), `districts` или `radius`."""
    categories: int
    has_budget: bool
    urgent_only: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertsMatched(DomainEvent):
    """Опубликованная заявка подошла подписчикам (`jobs.match_alerts`, 5.7): скольким — сразу
    (B1 поставлен) и подборкой. Одно событие на заявку: в аналитику — `job_matched_notified`."""

    event_type = "jobs.AlertsMatched"
    job_id: UUID
    client_id: UserId
    category_id: CategoryId
    city_id: CityId
    urgency: str
    instant: int
    digest: int
