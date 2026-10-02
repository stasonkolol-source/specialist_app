"""Убрать из избранного (DEVELOPMENT_PLAN 4.6): сердечко на S05, S08 и S12. Чего нет — без ошибки:
повтор запроса (двойное нажатие, сеть) не ломает экран."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.search.application.ports import Favorites
from app.modules.search.domain.favorites import FavoriteType
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoveFavoriteCommand:
    actor_id: UserId
    target_type: FavoriteType
    target_id: UUID


class RemoveFavorite:
    def __init__(self, favorites: Favorites, uow: UnitOfWork) -> None:
        self._favorites, self._uow = favorites, uow

    async def __call__(self, cmd: RemoveFavoriteCommand) -> None:
        async with self._uow:
            await self._favorites.remove(cmd.actor_id, cmd.target_type, cmd.target_id)
