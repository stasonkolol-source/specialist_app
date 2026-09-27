"""Уровни доверия (ARCHITECTURE §13.2, ADR-0016): от них зависят лимиты и модерация.

Уровень хранится в `users.trust_level` и попадает в клейм `tl` при выпуске access.
Правила пересчёта подключают шаги: 2.9 — телефон, 2.5a — срок без жалоб и понижение
санкцией или подтверждённой жалобой, 6.1a — завершённые сделки. До них уровень — 0.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import IntEnum


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
    confirmed_complaints: int = 0
    active_sanctions: int = 0
    completed_deals: int = 0


TrustRule = Callable[[TrustSignals], TrustLevel]
"""Повышение — уровень, который даёт правило (NEW — не применимо).
Ограничение — потолок уровня (TRUSTED — не ограничивает)."""
