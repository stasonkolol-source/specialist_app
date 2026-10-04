"""Лист ожидания Pro (Q24, DEVELOPMENT_PLAN 2.8a → 2.7b): «Хочу узнать первым» в рассылке.

Умолчание плана: отметка `pro_waitlist_at` в профиле исполнителя и событие `ProWaitlistJoined`
(аналитика `pro_waitlist_joined`). Повторное нажатие ничего не меняет и событие не повторяет.
Без профиля исполнителя в лист не встать: Pro — тариф исполнителя.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.modules.specialists.application.ports import ProfileRepository
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


class WaitlistOutcome(StrEnum):
    JOINED = "joined"
    ALREADY = "already"
    NO_PROFILE = "no_profile"


@dataclass(frozen=True, slots=True, kw_only=True)
class JoinProWaitlistCommand:
    user_id: UserId
    broadcast_id: UUID | None = None


class JoinProWaitlist:
    def __init__(self, uow: UnitOfWork, profiles: ProfileRepository, clock: Clock) -> None:
        self._uow, self._profiles, self._clock = uow, profiles, clock

    async def __call__(self, cmd: JoinProWaitlistCommand) -> WaitlistOutcome:
        async with self._uow:
            profile = await self._profiles.of_user(cmd.user_id)
            if profile is None:
                return WaitlistOutcome.NO_PROFILE
            if not profile.join_pro_waitlist(now=self._clock.now(), broadcast_id=cmd.broadcast_id):
                return WaitlistOutcome.ALREADY
            await self._profiles.save(profile)
        return WaitlistOutcome.JOINED
