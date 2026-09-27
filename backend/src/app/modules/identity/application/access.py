"""Проверка санкций: какие виды блокируют какое действие (ADR-0009, §13.2)."""

from collections.abc import Mapping
from datetime import datetime
from typing import Final

from app.modules.identity.api import Action
from app.modules.identity.domain.restriction import (
    ACCOUNT_BLOCKING,
    Restriction,
    RestrictionKind,
    blocking,
)
from app.platform.kernel.errors import RestrictedError

BLOCKED_BY: Final[Mapping[Action, frozenset[RestrictionKind]]] = {
    Action.LOGIN: ACCOUNT_BLOCKING,
    Action.POST: ACCOUNT_BLOCKING | {RestrictionKind.POSTING_BLOCKED},
    Action.RESPOND: ACCOUNT_BLOCKING | {RestrictionKind.RESPONDING_BLOCKED},
    Action.MESSAGE: ACCOUNT_BLOCKING | {RestrictionKind.MESSAGING_BLOCKED},
}


def ensure_allowed(restrictions: list[Restriction], action: Action, now: datetime) -> None:
    found = blocking(restrictions, BLOCKED_BY[action], now)
    if found is not None:
        raise RestrictedError(restriction=found.kind.value, until=found.ends_at)
