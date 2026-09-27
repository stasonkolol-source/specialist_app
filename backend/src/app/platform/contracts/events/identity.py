"""События модуля identity (ADR-0020 §2)."""

from dataclasses import dataclass

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class UserRegistered(DomainEvent):
    """Новый аккаунт: первый вход через провайдера `provider` (сейчас — telegram)."""

    event_type = "identity.UserRegistered"
    user_id: UserId
    provider: str
