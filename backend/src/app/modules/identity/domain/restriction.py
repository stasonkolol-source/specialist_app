"""Санкции (identity.restrictions, ADR-0009): единая точка проверки «можно ли».

Санкции создаёт модерация (шаг 2.5a); здесь — чтение и правило «какая санкция блокирует».
`shadow_banned` действий не запрещает: контент тихо скрывается от других.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RestrictionKind(StrEnum):
    POSTING_BLOCKED = "posting_blocked"
    RESPONDING_BLOCKED = "responding_blocked"
    MESSAGING_BLOCKED = "messaging_blocked"
    SHADOW_BANNED = "shadow_banned"
    SUSPENDED = "suspended"
    BANNED = "banned"


class RestrictionSource(StrEnum):
    MODERATION = "moderation"
    SYSTEM = "system"


ACCOUNT_BLOCKING = frozenset({RestrictionKind.SUSPENDED, RestrictionKind.BANNED})
"""Блокируют весь аккаунт: вход, refresh и любое действие."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Restriction:
    kind: RestrictionKind
    reason_code: str
    starts_at: datetime
    ends_at: datetime | None = None

    def is_active(self, now: datetime) -> bool:
        return self.starts_at <= now and (self.ends_at is None or now < self.ends_at)


def blocking(
    restrictions: Iterable[Restriction], kinds: frozenset[RestrictionKind], now: datetime
) -> Restriction | None:
    """Действующая санкция из `kinds`: бессрочная важнее срочной, дальняя — ближней."""
    active = [r for r in restrictions if r.kind in kinds and r.is_active(now)]
    if not active:
        return None
    return max(active, key=lambda r: (r.ends_at is None, r.ends_at or r.starts_at))
