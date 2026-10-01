"""Сигналы риска (ARCHITECTURE §13.3, §7.3 `moderation.risk_signals`).

Сигнал — факт о пользователе для уровня доверия, антиспама и антифрода: систематические
429, подтверждённая жалоба, контакты и предоплата в тексте (2.6), повторная регистрация
после удаления (2.12). Один и тот же факт пишется один раз (`dedupe_key`).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Final
from uuid import UUID

from app.platform.kernel.ids import UserId


class RiskSignalKind(StrEnum):
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    REPORT_CONFIRMED = "report_confirmed"
    CONTACT_LEAK = "contact_leak"
    PREPAYMENT_REQUEST = "prepayment_request"
    REREGISTERED_AFTER_DELETION = "reregistered_after_deletion"


SYSTEMATIC_429: Final = 5
"""Сколько 429 одного лимита за сутки — уже система, а не случайность **[Допущение]**:
человек, который упёрся в лимит, отступает после двух-трёх ответов, скрипт — нет."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RiskSignal:
    user_id: UserId
    kind: RiskSignalKind
    weight: float = 1.0
    ref_type: str | None = None
    ref_id: UUID | None = None
    details: Mapping[str, object] = field(default_factory=dict)
    dedupe_key: str | None = None
    """Один факт — один сигнал: повтор с тем же ключом не пишется."""


def rate_limit_signals(user_id: UserId, day: date, exceeded: Mapping[str, int]) -> list[RiskSignal]:
    """Сигнал на каждый лимит, в который пользователь упёрся систематически за `day` (UTC)."""
    return [
        RiskSignal(
            user_id=user_id,
            kind=RiskSignalKind.RATE_LIMIT_EXCEEDED,
            details={"rate": rate, "count": count, "day": day.isoformat()},
            dedupe_key=f"{RiskSignalKind.RATE_LIMIT_EXCEEDED}:{day:%Y%m%d}:{rate}:{user_id}",
        )
        for rate, count in sorted(exceeded.items())
        if count >= SYSTEMATIC_429
    ]
