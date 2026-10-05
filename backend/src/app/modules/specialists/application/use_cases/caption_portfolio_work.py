"""Подпись работы (S37, PATCH /me/profile/portfolio/{id}); пустая — без подписи. Новая подпись
уходит на проверку (план 6.7): у ждущей проверки — до публикации, у опубликованной —
пост-модерация, работа остаётся видна."""

from dataclasses import dataclass

from app.modules.identity.api import Action, IdentityApi
from app.modules.specialists.application.ports import PortfolioRepository, ProfileRepository
from app.modules.specialists.application.profiles import own_profile, request_work_review
from app.modules.specialists.domain.portfolio import PortfolioItem, PortfolioItemId
from app.modules.specialists.errors import PortfolioItemNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptionPortfolioWorkCommand:
    actor_id: UserId
    item_id: PortfolioItemId
    caption: str | None


class CaptionPortfolioWork:
    def __init__(
        self,
        uow: UnitOfWork,
        profiles: ProfileRepository,
        portfolio: PortfolioRepository,
        clock: Clock,
        identity: IdentityApi,
    ) -> None:
        self._uow, self._profiles, self._portfolio = uow, profiles, portfolio
        self._clock = clock
        self._identity = identity

    async def __call__(self, cmd: CaptionPortfolioWorkCommand) -> PortfolioItem:
        # санкция на публикацию и галочка S02c — как у создания профиля (SEC-01)
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        async with self._uow:
            profile = await own_profile(self._profiles, cmd.actor_id)
            profile.ensure_editable()
            items = await self._portfolio.list_for_update(profile.id)
            item = next((work for work in items if work.id == cmd.item_id), None)
            if item is None:
                raise PortfolioItemNotFoundError(item_id=cmd.item_id)
            if item.recaption(cmd.caption):
                await self._portfolio.save(item)
                request_work_review(self._uow, item, cmd.actor_id, now=self._clock.now())
        return item
