"""Избранное удалённого аккаунта (ARCHITECTURE §7.10; DEVELOPMENT_PLAN 2.12a, 4.6): удаляется
по событию UserDeleted вместе с остальными данными пользователя."""

from dataclasses import dataclass

from app.modules.search.application.ports import Favorites
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ForgetFavoritesCommand:
    user_id: UserId


class ForgetFavorites:
    def __init__(self, favorites: Favorites, uow: UnitOfWork) -> None:
        self._favorites, self._uow = favorites, uow

    async def __call__(self, cmd: ForgetFavoritesCommand) -> None:
        async with self._uow:
            await self._favorites.forget(cmd.user_id)
