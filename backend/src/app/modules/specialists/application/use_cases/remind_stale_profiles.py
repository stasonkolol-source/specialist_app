"""Напомнить о давно не обновлённом профиле (`specialists.stale_profile_reminders`; DEVELOPMENT_PLAN
5.7, перенесено из 2.10; ARCHITECTURE §11.3, §12.3).

Раз в день в 11:00 по Белграду: опубликованному профилю, который не менялся STALE_AFTER (ни
правки, ни «доступен сегодня» — любое изменение строки профиля), сейчас не «доступен» и не в
отпуске, — событие ProfileStale: notifications пришлёт «Включить «Доступен сегодня»» и «Обновить
профиль». Не чаще раза в REMIND_EVERY: отметка `stale_reminded_at` — в той же транзакции, что
событие. Пачками по CHUNK, каждая — своей транзакцией; занятые правкой профили — завтра.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from app.modules.specialists.application.ports import ProfileRepository
from app.platform.contracts.events.specialists import ProfileStale
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import BUSINESS_TZ, Clock

STALE_AFTER: Final = timedelta(days=30)
REMIND_EVERY: Final = timedelta(days=14)
REMIND_HOUR: Final = 11
"""Час напоминания по Белграду: задача стоит на 09:05 и 10:05 UTC, работает та, что в 11."""
CHUNK: Final = 200


@dataclass(frozen=True, slots=True, kw_only=True)
class RemindStaleProfilesCommand:
    limit: int = 5_000
    any_hour: bool = False
    """Не сверять час (тесты и `cli`): напомнить сейчас."""


class RemindStaleProfiles:
    def __init__(self, uow: UnitOfWork, profiles: ProfileRepository, clock: Clock) -> None:
        self._uow, self._profiles, self._clock = uow, profiles, clock

    async def __call__(self, cmd: RemindStaleProfilesCommand) -> int:
        """Скольким специалистам ушло напоминание."""
        now = self._clock.now()
        if not cmd.any_hour and now.astimezone(BUSINESS_TZ).hour != REMIND_HOUR:
            return 0
        reminded = 0
        while reminded < cmd.limit:
            chunk = min(CHUNK, cmd.limit - reminded)
            async with self._uow:
                stale = await self._profiles.stale(
                    updated_before=now - STALE_AFTER,
                    reminded_before=now - REMIND_EVERY,
                    now=now,
                    limit=chunk,
                )
                await self._profiles.mark_reminded([profile_id for profile_id, _ in stale], now)
                for profile_id, user_id in stale:
                    self._uow.add_event(
                        ProfileStale(profile_id=profile_id, user_id=user_id, occurred_at=now)
                    )
            reminded += len(stale)
            if len(stale) < chunk:
                break
        return reminded
