"""Санкции: какая блокирует какое действие (DEVELOPMENT_PLAN 0.15a, ADR-0009)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.identity.api import Action
from app.modules.identity.application.access import ensure_allowed
from app.modules.identity.domain.restriction import Restriction, RestrictionKind, blocking
from app.platform.kernel.errors import RestrictedError

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
DAY = timedelta(days=1)


def restriction(
    kind: RestrictionKind, *, starts: timedelta = -DAY, ends: timedelta | None = DAY
) -> Restriction:
    return Restriction(
        kind=kind,
        reason_code="spam",
        starts_at=NOW + starts,
        ends_at=NOW + ends if ends is not None else None,
    )


@pytest.mark.parametrize(
    ("kind", "blocked"),
    [
        (RestrictionKind.POSTING_BLOCKED, {Action.POST}),
        (RestrictionKind.RESPONDING_BLOCKED, {Action.RESPOND}),
        (RestrictionKind.MESSAGING_BLOCKED, {Action.MESSAGE}),
        (RestrictionKind.SHADOW_BANNED, set()),
        (RestrictionKind.SUSPENDED, set(Action)),
        (RestrictionKind.BANNED, set(Action)),
    ],
)
def test_each_kind_blocks_its_actions(kind: RestrictionKind, blocked: set[Action]) -> None:
    for action in Action:
        if action in blocked:
            with pytest.raises(RestrictedError) as caught:
                ensure_allowed([restriction(kind)], action, NOW)
            assert caught.value.restriction == kind.value
            assert caught.value.until == NOW + DAY
        else:
            ensure_allowed([restriction(kind)], action, NOW)


def test_only_active_restrictions_count() -> None:
    future = restriction(RestrictionKind.BANNED, starts=DAY, ends=None)
    past = restriction(RestrictionKind.BANNED, starts=-2 * DAY, ends=-DAY)
    ensure_allowed([future, past], Action.LOGIN, NOW)
    ends_now = restriction(RestrictionKind.BANNED, ends=timedelta(0))
    ensure_allowed([ends_now], Action.LOGIN, NOW)


def test_permanent_restriction_wins_over_temporary() -> None:
    temporary = restriction(RestrictionKind.SUSPENDED, ends=3 * DAY)
    permanent = restriction(RestrictionKind.BANNED, ends=None)
    found = blocking([temporary, permanent], frozenset(RestrictionKind), NOW)
    assert found is permanent
    later = restriction(RestrictionKind.SUSPENDED, ends=5 * DAY)
    assert blocking([temporary, later], frozenset(RestrictionKind), NOW) is later
