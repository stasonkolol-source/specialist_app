"""Аккаунт удалён (подписчик UserDeleted; ARCHITECTURE §7.10): профиль исполнителя снят с
каталога, удалён и обезличен, работы портфолио удалены. Прайс удаляет pricing по
ProfileDeleted, файлы работ и фото — media по UserDeleted. Профиля нет или он уже удалён —
ничего: повтор задачи безопасен.
"""

from dataclasses import dataclass

from app.modules.specialists.application.ports import PortfolioRepository, ProfileRepository
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ForgetProfileCommand:
    user_id: UserId


class ForgetProfile:
    def __init__(
        self,
        uow: UnitOfWork,
        profiles: ProfileRepository,
        portfolio: PortfolioRepository,
        clock: Clock,
    ) -> None:
        self._uow, self._profiles, self._portfolio, self._clock = uow, profiles, portfolio, clock

    async def __call__(self, cmd: ForgetProfileCommand) -> bool:
        """Был ли профиль."""
        now = self._clock.now()
        async with self._uow:
            profile = await self._profiles.of_user(cmd.user_id)
            if profile is None:
                return False
            for work in await self._portfolio.list_for_update(profile.id):
                work.recaption(None)
                work.remove(now=now)
                await self._portfolio.save(work)
            profile.forget(now=now)
            await self._profiles.save(profile)
        return True
