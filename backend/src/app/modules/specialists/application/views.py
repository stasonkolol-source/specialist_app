"""Свой профиль для кабинета: запрос плюс прайс — «чего не хватает» как при отправке."""

from dataclasses import replace

from app.modules.specialists.api import PriceList
from app.modules.specialists.application.dto import ProfileView
from app.modules.specialists.application.ports import ProfileQuery
from app.modules.specialists.domain.profile import ProfileKind
from app.platform.kernel.ids import UserId


class ProfileViews:
    def __init__(self, query: ProfileQuery, prices: PriceList) -> None:
        self._query, self._prices = query, prices

    async def of_user(self, user_id: UserId) -> ProfileView | None:
        view = await self._query.of_user(user_id)
        if view is None or view.kind is not ProfileKind.PRO:
            return view
        if await self._prices.has_items(view.id):
            return view
        return replace(view, missing=(*view.missing, "services"))
