"""Пересчёт уровня доверия (ADR-0016 §2, ARCHITECTURE §13.2): политика `trust_level`.

Факты — у identity: возраст аккаунта, последнее нарушение (`users.trust_penalty_at`) и
действующие санкции (identity.restrictions). Модерация сообщает о нарушениях через фасад
(`restrict`, `record_violation`), а поднимает уровень ежедневный `identity.trust_aging`.
"""

from datetime import datetime

from app.modules.identity.application.ports import IdentityQuery
from app.modules.identity.domain.policies import trust_level
from app.modules.identity.domain.user import User


class TrustRecalculation:
    def __init__(self, query: IdentityQuery) -> None:
        self._query = query

    async def apply(self, user: User, *, now: datetime) -> None:
        """Пересчитать уровень пользователя в текущей транзакции (санкции уже записаны)."""
        restrictions = await self._query.restrictions(user.id, now)
        active = sum(1 for restriction in restrictions if restriction.is_active(now))
        signals = user.trust_signals(now=now, active_sanctions=active)
        user.apply_trust_level(trust_level(signals), now=now)
