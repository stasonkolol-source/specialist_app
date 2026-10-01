"""Лестница санкций (ADR-0016 §4, ARCHITECTURE §14.4).

Лёгкое нарушение — следующая ступень: предупреждение → страйк 1 (лимиты новичка на 7 дней)
→ страйк 2 (запрет откликов на 30 дней) → страйк 3 (бан). Ступень считают предупреждения и
страйки за последние 180 дней: старые сгорают. Серьёзное (увод на предоплату, накрутка,
фейковое портфолио) — сразу приостановка до проверки; P0 — бан.

Здесь — какая ступень и что она значит. Санкцию на аккаунт ставит фасад identity
(`identity.restrictions`), модерация хранит историю ступеней (`moderation.sanctions`).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from app.platform.contracts.events.identity import RestrictionKind
from app.platform.kernel.ids import CaseId, RestrictionId, UserId


class Severity(StrEnum):
    MINOR = "minor"
    """Лёгкое: следующая ступень лестницы."""
    SERIOUS = "serious"
    """Серьёзное: приостановка аккаунта до проверки."""
    CRITICAL = "critical"
    """P0: бан."""


class SanctionStep(StrEnum):
    WARNING = "warning"
    STRIKE_1 = "strike_1"
    STRIKE_2 = "strike_2"
    BAN = "ban"
    SUSPENSION = "suspension"


LADDER: Final = (
    SanctionStep.WARNING,
    SanctionStep.STRIKE_1,
    SanctionStep.STRIKE_2,
    SanctionStep.BAN,
)
COUNTED: Final = frozenset(LADDER[:-1])
"""Ступени, которые сгорают и считаются для следующей: предупреждение и страйки 1–2."""
STRIKE_TTL: Final = timedelta(days=180)


@dataclass(frozen=True, slots=True)
class Effect:
    """Что ступень делает с аккаунтом: вид санкции identity и срок (None — бессрочно)."""

    kind: RestrictionKind
    duration: timedelta | None = None


EFFECTS: Final[Mapping[SanctionStep, Effect]] = {
    SanctionStep.STRIKE_1: Effect(RestrictionKind.LIMITED, timedelta(days=7)),
    SanctionStep.STRIKE_2: Effect(RestrictionKind.RESPONDING_BLOCKED, timedelta(days=30)),
    SanctionStep.BAN: Effect(RestrictionKind.BANNED),
    SanctionStep.SUSPENSION: Effect(RestrictionKind.SUSPENDED),
}
"""Предупреждения в списке нет: оно ничего не запрещает, только опускает уровень доверия."""


def next_step(severity: Severity, counted: int) -> SanctionStep:
    """Ступень за нарушение; `counted` — предупреждений и страйков 1–2 за 180 дней."""
    if severity is Severity.CRITICAL:
        return SanctionStep.BAN
    if severity is Severity.SERIOUS:
        return SanctionStep.SUSPENSION
    return LADDER[min(counted, len(LADDER) - 1)]


@dataclass(frozen=True, slots=True, kw_only=True)
class Sanction:
    """Ступень лестницы, назначенная решением по кейсу."""

    user_id: UserId
    case_id: CaseId
    step: SanctionStep
    created_at: datetime
    expires_at: datetime | None
    """Когда ступень сгорает; бан и приостановка не сгорают."""
    restriction_id: RestrictionId | None = None
    """Санкция identity, если ступень что-то запрещает."""

    @classmethod
    def impose(
        cls,
        *,
        user_id: UserId,
        case_id: CaseId,
        step: SanctionStep,
        now: datetime,
        restriction_id: RestrictionId | None,
    ) -> Sanction:
        expires_at = now + STRIKE_TTL if step in COUNTED else None
        return cls(
            user_id=user_id,
            case_id=case_id,
            step=step,
            created_at=now,
            expires_at=expires_at,
            restriction_id=restriction_id,
        )
