"""Избранные специалисты S12 (DEVELOPMENT_PLAN 4.6): карточки, как в выдаче, новые первыми.

Показываются те, кто виден в каталоге сейчас: скрытый или снятый профиль из списка пропадает,
а запись остаётся — профиль вернулся, вернулся и в избранное. Расстояния нет: точки клиента у
списка нет.
"""

from dataclasses import dataclass

from app.modules.media.api import MediaApi
from app.modules.search.application.cards import specialist_cards
from app.modules.search.application.dto import SpecialistCard
from app.modules.search.application.ports import Favorites, SpecialistSearch
from app.modules.search.domain.favorites import FavoriteType
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ListFavoritesCommand:
    actor_id: UserId


class ListFavorites:
    def __init__(
        self, favorites: Favorites, search: SpecialistSearch, media: MediaApi, clock: Clock
    ) -> None:
        self._favorites, self._search, self._media, self._clock = favorites, search, media, clock

    async def __call__(self, cmd: ListFavoritesCommand) -> list[SpecialistCard]:
        ids = await self._favorites.ids(cmd.actor_id, FavoriteType.PROFILE)
        hits = {hit.profile_id: hit for hit in await self._search.listed(ids)}
        shown = [hits[profile_id] for profile_id in ids if profile_id in hits]
        return await specialist_cards(shown, self._media, self._clock.now())
