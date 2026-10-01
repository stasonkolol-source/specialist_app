"""События модуля specialists (ADR-0020 §2, ARCHITECTURE §5.3).

Подписчики: read-model поиска (4.1), уведомления (публикация профиля), аналитика.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileSubmitted(DomainEvent):
    """Профиль отправлен на проверку: новый, после правок по отказу или переход в «Специалист»."""

    event_type = "specialists.ProfileSubmitted"
    profile_id: UUID
    user_id: UserId
    kind: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfilePublished(DomainEvent):
    """Профиль виден в каталоге. `approved` — его только что одобрила модерация (а не
    владелец вернул скрытый): тогда автору уходит уведомление о публикации."""

    event_type = "specialists.ProfilePublished"
    profile_id: UUID
    user_id: UserId
    approved: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileUpdated(DomainEvent):
    """Изменились поля профиля (`fields`): проекции обновляют свои копии."""

    event_type = "specialists.ProfileUpdated"
    profile_id: UUID
    user_id: UserId
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ProfileHidden(DomainEvent):
    """Профиль больше не в каталоге: скрыл владелец или модерация (`by_moderation`)."""

    event_type = "specialists.ProfileHidden"
    profile_id: UUID
    user_id: UserId
    by_moderation: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class AvailabilityChanged(DomainEvent):
    """«Доступен сегодня до …» включили, поменяли или сняли (`available_until` = None):
    владелец в S38 и боте или срок истёк."""

    event_type = "specialists.AvailabilityChanged"
    profile_id: UUID
    user_id: UserId
    available_until: datetime | None
