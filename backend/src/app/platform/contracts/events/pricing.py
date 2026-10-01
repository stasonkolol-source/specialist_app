"""События модуля pricing (ADR-0020 §2). Подписчик — read-model поиска (4.1: цена «от»)."""

from dataclasses import dataclass
from uuid import UUID

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceListChanged(DomainEvent):
    """Прайс профиля изменился: позиция добавлена, изменена, удалена или порядок."""

    event_type = "pricing.PriceListChanged"
    profile_id: UUID
    user_id: UserId
