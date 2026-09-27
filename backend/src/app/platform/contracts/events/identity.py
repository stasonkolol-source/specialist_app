"""События модуля identity (ADR-0020 §2).

`RestrictionKind` — часть published language: вид санкции ставит модерация через фасад
identity, а подписчики (уведомления, модерация) получают его в `UserRestricted`.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import RestrictionId, UserId


class RestrictionKind(StrEnum):
    """Вид санкции в identity.restrictions (ADR-0009, ADR-0016)."""

    POSTING_BLOCKED = "posting_blocked"
    RESPONDING_BLOCKED = "responding_blocked"
    MESSAGING_BLOCKED = "messaging_blocked"
    SHADOW_BANNED = "shadow_banned"
    SUSPENDED = "suspended"
    BANNED = "banned"


@dataclass(frozen=True, slots=True, kw_only=True)
class UserRegistered(DomainEvent):
    """Новый аккаунт: первый вход через провайдера `provider` (сейчас — telegram)."""

    event_type = "identity.UserRegistered"
    user_id: UserId
    provider: str


@dataclass(frozen=True, slots=True, kw_only=True)
class UserUpdated(DomainEvent):
    """Изменился профиль пользователя: проекции обновляют копии нужных им полей.

    `fields` — имена изменённых полей (`display_name`, `ui_locale`, `home_city_id`,
    `intent`, `trust_level`): подписчик пропускает событие, если его поля не менялись.
    """

    event_type = "identity.UserUpdated"
    user_id: UserId
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class UserRestricted(DomainEvent):
    """На пользователя наложена санкция (identity.restrictions).

    `until` — до когда; None — бессрочно. `case_id` — кейс модерации, если он есть.
    Подписчики: уведомление `account.restricted` (2.3), отзыв сессий при бане (2.5a).
    """

    event_type = "identity.UserRestricted"
    user_id: UserId
    restriction_id: RestrictionId
    kind: RestrictionKind
    reason_code: str
    until: datetime | None
    case_id: UUID | None
