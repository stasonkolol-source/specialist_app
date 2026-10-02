"""Избранное (DEVELOPMENT_PLAN 4.6): только видимые специалисты, без дублей и ошибок повтора,
не больше 100, в S12 — новые первыми и только те, кто виден в каталоге сейчас."""

from uuid import UUID

import pytest

from app.modules.search.application.use_cases.add_favorite import AddFavorite, AddFavoriteCommand
from app.modules.search.application.use_cases.forget_favorites import (
    ForgetFavorites,
    ForgetFavoritesCommand,
)
from app.modules.search.application.use_cases.list_favorites import (
    ListFavorites,
    ListFavoritesCommand,
)
from app.modules.search.application.use_cases.remove_favorite import (
    RemoveFavorite,
    RemoveFavoriteCommand,
)
from app.modules.search.domain.favorites import MAX_FAVORITES, FavoriteType
from app.modules.search.errors import FavoritesFullError
from app.modules.search.tests.fakes import FakeFavorites, FakeMedia, FakeSearch, FakeUoW
from app.modules.search.tests.unit.test_search_specialists import NOW, hit
from app.platform.kernel.errors import NotFoundError
from app.platform.kernel.ids import UserId
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.unit

USER = UserId(UUID(int=1000))
PROFILE = FavoriteType.PROFILE


class Favorites:
    def __init__(self, visible: int = 3) -> None:
        self.search = FakeSearch(visible={UUID(int=n): hit(n) for n in range(1, visible + 1)})
        self.rows, self.uow = FakeFavorites(), FakeUoW()

    async def add(self, number: int) -> None:
        use_case = AddFavorite(self.rows, self.search, self.uow)
        await use_case(
            AddFavoriteCommand(actor_id=USER, target_type=PROFILE, target_id=UUID(int=number))
        )

    async def remove(self, number: int) -> None:
        use_case = RemoveFavorite(self.rows, self.uow)
        await use_case(
            RemoveFavoriteCommand(actor_id=USER, target_type=PROFILE, target_id=UUID(int=number))
        )

    async def shown(self) -> list[str]:
        listing = ListFavorites(self.rows, self.search, FakeMedia(), FakeClock(NOW))
        return [card.display_name for card in await listing(ListFavoritesCommand(actor_id=USER))]


async def test_saved_specialists_come_newest_first() -> None:
    favorites = Favorites()

    await favorites.add(1)
    await favorites.add(3)
    await favorites.add(1)

    assert await favorites.shown() == ["Мастер 3", "Мастер 1"]


async def test_hidden_or_unknown_specialist_cannot_be_saved() -> None:
    favorites = Favorites(visible=1)

    with pytest.raises(NotFoundError):
        await favorites.add(2)


async def test_specialist_hidden_later_drops_out_of_the_list_but_stays_saved() -> None:
    favorites = Favorites()
    await favorites.add(1)
    await favorites.add(2)

    hidden = favorites.search.visible.pop(UUID(int=2))
    assert await favorites.shown() == ["Мастер 1"]
    favorites.search.visible[UUID(int=2)] = hidden
    assert await favorites.shown() == ["Мастер 2", "Мастер 1"]


async def test_removing_twice_is_fine() -> None:
    favorites = Favorites()
    await favorites.add(1)

    await favorites.remove(1)
    await favorites.remove(1)

    assert await favorites.shown() == []


async def test_no_more_than_the_limit_but_resaving_is_fine() -> None:
    favorites = Favorites(visible=MAX_FAVORITES + 1)
    for number in range(1, MAX_FAVORITES + 1):
        await favorites.add(number)

    await favorites.add(1)
    with pytest.raises(FavoritesFullError):
        await favorites.add(MAX_FAVORITES + 1)


async def test_deleted_account_loses_its_favorites() -> None:
    favorites = Favorites()
    await favorites.add(1)

    await ForgetFavorites(favorites.rows, favorites.uow)(ForgetFavoritesCommand(user_id=USER))

    assert favorites.rows.rows == []
