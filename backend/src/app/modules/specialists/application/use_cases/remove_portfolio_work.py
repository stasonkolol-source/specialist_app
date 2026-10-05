"""Убрать работу (S37, DELETE /me/profile/portfolio/{id}): работа исчезает, позиции
остальных сдвигаются; файл удаляет media — задачей в той же транзакции."""

from dataclasses import dataclass

from app.modules.identity.api import Action, IdentityApi
from app.modules.media.api import MediaApi
from app.modules.specialists.application.ports import PortfolioRepository, ProfileRepository
from app.modules.specialists.application.profiles import own_profile
from app.modules.specialists.domain.portfolio import PortfolioItemId
from app.modules.specialists.errors import PortfolioItemNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class RemovePortfolioWorkCommand:
    actor_id: UserId
    item_id: PortfolioItemId


class RemovePortfolioWork:
    def __init__(
        self,
        uow: UnitOfWork,
        profiles: ProfileRepository,
        portfolio: PortfolioRepository,
        media: MediaApi,
        clock: Clock,
        identity: IdentityApi,
    ) -> None:
        self._uow, self._profiles, self._portfolio = uow, profiles, portfolio
        self._media, self._clock = media, clock
        self._identity = identity

    async def __call__(self, cmd: RemovePortfolioWorkCommand) -> None:
        # санкция на публикацию и галочка S02c — как у создания профиля (SEC-01)
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        async with self._uow:
            profile = await own_profile(self._profiles, cmd.actor_id)
            items = await self._portfolio.list_for_update(profile.id)
            removed = next((item for item in items if item.id == cmd.item_id), None)
            if removed is None:
                raise PortfolioItemNotFoundError(item_id=cmd.item_id)
            removed.remove(now=self._clock.now())
            await self._portfolio.save(removed)
            rest = [item for item in items if item.id != cmd.item_id]
            for position, item in enumerate(rest):
                if item.position != position:
                    item.position = position
                    await self._portfolio.save(item)
            await self._media.discard(cmd.actor_id, removed.media_id)
