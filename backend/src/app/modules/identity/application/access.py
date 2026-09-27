"""Единая точка «можно ли» (ADR-0009, ARCHITECTURE §13.2): санкции и согласия.

Порядок проверки: сначала санкция (403 `restricted`: экран ограничения важнее онбординга),
затем согласия для создающих действий (403 `consent_required`: показать S02c). Вход
(LOGIN) согласия не требует — гость смотрит каталог.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Final

from app.modules.identity.api import Action
from app.modules.identity.application.dto import AccessView
from app.modules.identity.application.ports import IdentityQuery
from app.modules.identity.domain.policies import (
    accepted_versions,
    missing_consents,
    required_consents,
)
from app.modules.identity.domain.restriction import (
    ACCOUNT_BLOCKING,
    Restriction,
    RestrictionKind,
    blocking,
)
from app.modules.identity.errors import ConsentRequiredError
from app.platform.config.port import LegalVersions
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import RestrictedError
from app.platform.kernel.ids import UserId

BLOCKED_BY: Final[Mapping[Action, frozenset[RestrictionKind]]] = {
    Action.LOGIN: ACCOUNT_BLOCKING,
    Action.POST: ACCOUNT_BLOCKING | {RestrictionKind.POSTING_BLOCKED},
    Action.RESPOND: ACCOUNT_BLOCKING | {RestrictionKind.RESPONDING_BLOCKED},
    Action.MESSAGE: ACCOUNT_BLOCKING | {RestrictionKind.MESSAGING_BLOCKED},
}

NEEDS_CONSENT: Final = frozenset({Action.POST, Action.RESPOND, Action.MESSAGE})
"""Создающие действия: без галочки S02c нельзя (PRODUCT: гость и клиент)."""


def ensure_allowed(restrictions: list[Restriction], action: Action, now: datetime) -> None:
    found = blocking(restrictions, BLOCKED_BY[action], now)
    if found is not None:
        raise RestrictedError(restriction=found.kind.value, until=found.ends_at)


class AccessChecker:
    """Проверка перед действием (фасад, use cases) и сводка возможностей для GET /me."""

    def __init__(self, query: IdentityQuery, legal: LegalVersions, clock: Clock) -> None:
        self._query, self._legal, self._clock = query, legal, clock

    async def ensure_allowed(self, user_id: UserId, action: Action) -> None:
        now = self._clock.now()
        ensure_allowed(await self._query.restrictions(user_id, now), action, now)
        if action in NEEDS_CONSENT:
            missing = missing_consents(
                await self._query.consents(user_id),
                required_consents(await self._legal.legal_versions()),
            )
            if missing:
                raise ConsentRequiredError(documents=sorted(d.value for d in missing))

    async def view(self, user_id: UserId) -> AccessView:
        now = self._clock.now()
        restrictions = await self._query.restrictions(user_id, now)
        consents = await self._query.consents(user_id)
        missing = missing_consents(consents, required_consents(await self._legal.legal_versions()))
        allowed = frozenset(
            action
            for action in Action
            if blocking(restrictions, BLOCKED_BY[action], now) is None
            and not (action in NEEDS_CONSENT and missing)
        )
        return AccessView(
            consents=accepted_versions(consents), consent_required=bool(missing), allowed=allowed
        )
