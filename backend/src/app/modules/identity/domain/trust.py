"""Уровни доверия (ARCHITECTURE §13.2, ADR-0016): от них зависят лимиты и модерация.

Уровень хранится в `users.trust_level` и попадает в клейм `tl` при выпуске access.
Правила пересчёта подключают шаги: 2.9 — телефон, 2.5a — срок без жалоб и понижение
санкцией или подтверждённой жалобой, 6.1a — завершённые сделки (факты —
`identity.completed_deals`, их пишет подписчик DealCompleted).

Нарушение (санкция модерации или подтверждённая жалоба) опускает уровень до 0 на
CLEAN_PERIOD: «≥ 14 дней без подтверждённых жалоб» считается от последнего нарушения, а
не только от регистрации. Поднимает уровень обратно ежедневный `identity.trust_aging`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import IntEnum
from typing import Final

CLEAN_PERIOD: Final = timedelta(days=14)
"""Сколько жить без нарушений до уровня 1 (ADR-0016 §2): от регистрации и от нарушения."""
VERIFIED_DEALS: Final = 3
"""Завершённых сделок до уровня 2 (ADR-0016 §2)."""


class TrustLevel(IntEnum):
    NEW = 0
    """Только Telegram-аккаунт."""
    BASIC = 1
    """Телефон подтверждён или ≥ 14 дней без подтверждённых жалоб."""
    VERIFIED = 2
    """≥ 3 завершённые сделки без подтверждённых жалоб."""
    TRUSTED = 3
    """KYC (v1) и ≥ 10 завершённых сделок."""


@dataclass(frozen=True, slots=True, kw_only=True)
class TrustSignals:
    """Факты о пользователе для пересчёта; источники подключают шаги 2.9, 2.5a, 6.1a."""

    account_age: timedelta
    phone_verified: bool = False
    penalized_ago: timedelta | None = None
    """Сколько прошло с последнего нарушения (санкция или подтверждённая жалоба); None —
    нарушений не было."""
    active_sanctions: int = 0
    """Санкции, которые действуют сейчас (identity.restrictions)."""
    completed_deals: int = 0


TrustRule = Callable[[TrustSignals], TrustLevel]
"""Повышение — уровень, который даёт правило (NEW — не применимо).
Ограничение — потолок уровня (TRUSTED — не ограничивает)."""
