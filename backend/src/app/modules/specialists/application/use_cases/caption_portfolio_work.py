"""Подпись работы (S37, PATCH /me/profile/portfolio/{id}); пустая — без подписи."""

from dataclasses import dataclass

from app.modules.specialists.application.ports import PortfolioRepository, ProfileRepository
from app.modules.specialists.application.profiles import own_profile
from app.modules.specialists.domain.portfolio import PortfolioItem, PortfolioItemId
from app.modules.specialists.errors import PortfolioItemNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptionPortfolioWorkCommand:
    actor_id: UserId
    item_id: PortfolioItemId
    caption: str | None


class CaptionPortfolioWork:
    def __init__(
        self, uow: UnitOfWork, profiles: ProfileRepository, portfolio: PortfolioRepository
    ) -> None:
        self._uow, self._profiles, self._portfolio = uow, profiles, portfolio

    async def __call__(self, cmd: CaptionPortfolioWorkCommand) -> PortfolioItem:
        async with self._uow:
            profile = await own_profile(self._profiles, cmd.actor_id)
            profile.ensure_editable()
            items = await self._portfolio.list_for_update(profile.id)
            item = next((work for work in items if work.id == cmd.item_id), None)
            if item is None:
                raise PortfolioItemNotFoundError(item_id=cmd.item_id)
            if item.recaption(cmd.caption):
                await self._portfolio.save(item)
        return item
