"""Санкции (identity.restrictions, ADR-0009): единая точка проверки «можно ли».

Санкции ставит модерация (шаг 2.5a) через фасад identity; здесь — правило «какая санкция
что блокирует» и проверка новой санкции. `shadow_banned` действий не запрещает: контент
тихо скрывается от других. Вид санкции объявлен в контракте событий: его видят модерация
и подписчики `UserRestricted`.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from app.modules.identity.errors import InvalidRestrictionError
from app.platform.contracts.events.identity import RestrictionKind as RestrictionKind

MAX_REASON_CODE = 64
_REASON_CODE: Final = re.compile(r"[a-z][a-z0-9_.]*")
"""Код причины — машинный (`spam`, `prepayment_fraud`, `rules.3_2`): текст — в модерации."""


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

    @classmethod
    def impose(
        cls,
        *,
        kind: RestrictionKind,
        reason_code: str,
        now: datetime,
        ends_at: datetime | None = None,
    ) -> Restriction:
        """Новая санкция действует с `now`; `ends_at` None — бессрочно."""
        if len(reason_code) > MAX_REASON_CODE or not _REASON_CODE.fullmatch(reason_code):
            raise InvalidRestrictionError(field="reason_code")
        if ends_at is not None and ends_at <= now:
            raise InvalidRestrictionError(field="ends_at")
        return cls(kind=kind, reason_code=reason_code, starts_at=now, ends_at=ends_at)

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
