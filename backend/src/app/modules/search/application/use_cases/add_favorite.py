"""Добавить в избранное (DEVELOPMENT_PLAN 4.6): сердечко на S05 и S08.

Специалиста — только видимого в каталоге: скрытого или неизвестного нет (404, как его карточки).
Повторное добавление — без ошибки. Больше 100 записей одного типа — `favorites_full`.
Заявки — с шагом 5.3.
"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.search.application.ports import Favorites, SpecialistSearch
from app.modules.search.domain.favorites import MAX_FAVORITES, FavoriteType
from app.modules.search.errors import FavoritesFullError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.errors import NotFoundError
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class AddFavoriteCommand:
    actor_id: UserId
    target_type: FavoriteType
    target_id: UUID


class AddFavorite:
    def __init__(self, favorites: Favorites, search: SpecialistSearch, uow: UnitOfWork) -> None:
        self._favorites, self._search, self._uow = favorites, search, uow

    async def __call__(self, cmd: AddFavoriteCommand) -> None:
        if not await self._search.listed([cmd.target_id]):
            raise NotFoundError()
        async with self._uow:
            if await self._favorites.count(cmd.actor_id, cmd.target_type) >= MAX_FAVORITES:
                if cmd.target_id in await self._favorites.ids(cmd.actor_id, cmd.target_type):
                    return
                raise FavoritesFullError(limit=MAX_FAVORITES)
            await self._favorites.add(cmd.actor_id, cmd.target_type, cmd.target_id)
