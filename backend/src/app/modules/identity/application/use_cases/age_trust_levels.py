"""Уровень доверия 1 тем, кто 14 дней без нарушений (periodic `identity.trust_aging`).

ADR-0016 §2: базовый уровень — «≥ 14 дней на платформе без подтверждённых жалоб». Санкция и
подтверждённая жалоба опускают уровень сразу (фасад identity), а поднимает его обратно эта
задача раз в сутки. Кандидаты — по (created_at, id), порциями по CHUNK в своей транзакции,
до LIMIT за запуск: каждый кандидат проверяется один раз.
"""

from dataclasses import dataclass
from datetime import datetime

from app.modules.identity.application.ports import UserRepository
from app.modules.identity.application.trust import TrustRecalculation
from app.modules.identity.domain.trust import CLEAN_PERIOD, TrustLevel
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId

CHUNK = 100
LIMIT = 5_000


@dataclass(frozen=True, slots=True, kw_only=True)
class AgeTrustLevelsCommand:
    limit: int = LIMIT


class AgeTrustLevels:
    def __init__(
        self, uow: UnitOfWork, users: UserRepository, trust: TrustRecalculation, clock: Clock
    ) -> None:
        self._uow, self._users, self._trust, self._clock = uow, users, trust, clock

    async def __call__(self, cmd: AgeTrustLevelsCommand) -> int:
        """Скольким пользователям поднят уровень."""
        now = self._clock.now()
        after: tuple[datetime, UserId] | None = None
        checked = promoted = 0
        while checked < cmd.limit:
            async with self._uow:
                users = await self._users.trust_aging_candidates(
                    now=now,
                    clean_since=now - CLEAN_PERIOD,
                    after=after,
                    limit=min(CHUNK, cmd.limit - checked),
                )
                for user in users:
                    await self._trust.apply(user, now=now)
                    await self._users.save(user)
                    promoted += user.trust_level > TrustLevel.NEW
            checked += len(users)
            if len(users) < CHUNK:
                break
            after = (users[-1].created_at, users[-1].id)
        return promoted
