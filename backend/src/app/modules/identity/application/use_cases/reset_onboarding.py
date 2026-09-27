"""Онбординг заново — только dev: `cli dev-reset-user <telegram_id>` (DEVELOPMENT_PLAN 1.5b).

Владелец проходит S02a–c в Telegram ещё раз: у пользователя нет города и намерения, язык —
снова из клиента Telegram, согласия одной галочки отозваны (журнал остаётся, `withdrawn_at`).
Аккаунт, сессии и остальные данные не трогаются. Окружение проверяет точка входа (CLI):
на stage и prod команда не запускается.
"""

from dataclasses import dataclass

from app.modules.identity.application.dto import OnboardingReset
from app.modules.identity.application.ports import ConsentRepository, UserRepository
from app.modules.identity.domain.consent import ONE_TICK
from app.modules.identity.domain.user import AuthProvider
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class ResetOnboardingCommand:
    telegram_id: int
    """Кого сбросить: Telegram id владельца dev-бота (в логи не пишется)."""


class ResetOnboarding:
    def __init__(
        self, uow: UnitOfWork, users: UserRepository, consents: ConsentRepository, clock: Clock
    ) -> None:
        self._uow, self._users, self._consents, self._clock = uow, users, consents, clock

    async def __call__(self, cmd: ResetOnboardingCommand) -> OnboardingReset | None:
        """None — такой пользователь ещё не входил."""
        now = self._clock.now()
        async with self._uow:
            user = await self._users.find_by_identity(AuthProvider.TELEGRAM, str(cmd.telegram_id))
            if user is None:
                return None
            user.reset_onboarding(now=now)
            await self._users.save(user)
            withdrawn = await self._consents.withdraw(user.id, ONE_TICK, now=now)
        return OnboardingReset(user_id=user.id, withdrawn_consents=withdrawn)
