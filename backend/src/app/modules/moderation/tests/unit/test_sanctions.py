"""Лестница санкций (ADR-0016 §4) и сигналы риска по 429 (ARCHITECTURE §13.3)."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.modules.moderation.domain.risk import SYSTEMATIC_429, RiskSignalKind, rate_limit_signals
from app.modules.moderation.domain.sanctions import (
    EFFECTS,
    Sanction,
    SanctionStep,
    Severity,
    next_step,
)
from app.platform.contracts.events.identity import RestrictionKind
from app.platform.kernel.ids import CaseId, UserId, new_id

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("counted", "step"),
    [
        (0, SanctionStep.WARNING),
        (1, SanctionStep.STRIKE_1),
        (2, SanctionStep.STRIKE_2),
        (3, SanctionStep.BAN),
        (7, SanctionStep.BAN),
    ],
)
def test_minor_violations_climb_the_ladder(counted: int, step: SanctionStep) -> None:
    assert next_step(Severity.MINOR, counted) is step


def test_serious_and_critical_skip_the_ladder() -> None:
    assert next_step(Severity.SERIOUS, 0) is SanctionStep.SUSPENSION
    assert next_step(Severity.CRITICAL, 0) is SanctionStep.BAN


def test_steps_and_what_they_restrict() -> None:
    assert SanctionStep.WARNING not in EFFECTS  # предупреждение ничего не запрещает
    assert EFFECTS[SanctionStep.STRIKE_1].kind is RestrictionKind.LIMITED
    assert EFFECTS[SanctionStep.STRIKE_1].duration == timedelta(days=7)
    assert EFFECTS[SanctionStep.STRIKE_2].kind is RestrictionKind.RESPONDING_BLOCKED
    assert EFFECTS[SanctionStep.STRIKE_2].duration == timedelta(days=30)
    assert EFFECTS[SanctionStep.BAN].duration is None
    assert EFFECTS[SanctionStep.SUSPENSION].kind is RestrictionKind.SUSPENDED


@pytest.mark.parametrize(
    ("step", "expires"),
    [
        (SanctionStep.WARNING, NOW + timedelta(days=180)),
        (SanctionStep.STRIKE_2, NOW + timedelta(days=180)),
        (SanctionStep.BAN, None),
        (SanctionStep.SUSPENSION, None),
    ],
)
def test_warnings_and_strikes_burn_out_after_180_days(
    step: SanctionStep, expires: datetime | None
) -> None:
    sanction = Sanction.impose(
        user_id=UserId(new_id()),
        case_id=CaseId(new_id()),
        step=step,
        now=NOW,
        restriction_id=None,
    )
    assert sanction.expires_at == expires


def test_only_systematic_429_become_risk_signals() -> None:
    user = UserId(new_id())
    day = date(2026, 10, 1)

    signals = rate_limit_signals(
        user, day, {"media.uploads": SYSTEMATIC_429, "auth.ip": SYSTEMATIC_429 - 1}
    )

    [signal] = signals
    assert signal.kind is RiskSignalKind.RATE_LIMIT_EXCEEDED
    assert signal.details == {"rate": "media.uploads", "count": 5, "day": "2026-10-01"}
    assert signal.dedupe_key == f"rate_limit_exceeded:20261001:media.uploads:{user}"
