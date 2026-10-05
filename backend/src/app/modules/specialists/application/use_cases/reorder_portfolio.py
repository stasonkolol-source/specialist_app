"""Порядок работ (S37, PUT /me/profile/portfolio/order): весь список id в новом порядке."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.identity.api import Action, IdentityApi
from app.modules.specialists.application.ports import PortfolioRepository, ProfileRepository
from app.modules.specialists.application.profiles import own_profile
from app.modules.specialists.domain.portfolio import PortfolioItem, PortfolioItemId
from app.modules.specialists.errors import InvalidPortfolioError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ReorderPortfolioCommand:
    actor_id: UserId
    item_ids: Sequence[PortfolioItemId]


class ReorderPortfolio:
    def __init__(
        self,
        uow: UnitOfWork,
        profiles: ProfileRepository,
        portfolio: PortfolioRepository,
        identity: IdentityApi,
    ) -> None:
        self._uow, self._profiles, self._portfolio = uow, profiles, portfolio
        self._identity = identity

    async def __call__(self, cmd: ReorderPortfolioCommand) -> list[PortfolioItem]:
        # санкция на публикацию и галочка S02c — как у создания профиля (SEC-01)
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        async with self._uow:
            profile = await own_profile(self._profiles, cmd.actor_id)
            profile.ensure_editable()
            items = {item.id: item for item in await self._portfolio.list_for_update(profile.id)}
            if len(cmd.item_ids) != len(items) or set(cmd.item_ids) != set(items):
                raise InvalidPortfolioError(field="item_ids")
            ordered = [items[item_id] for item_id in cmd.item_ids]
            for position, item in enumerate(ordered):
                if item.position != position:
                    item.position = position
                    await self._portfolio.save(item)
        return ordered
