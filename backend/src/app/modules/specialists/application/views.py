"""Свой профиль для кабинета: запрос плюс прайс — «чего не хватает» как при отправке и полнота
профиля (S33)."""

from dataclasses import replace

from app.modules.specialists.api import PriceList
from app.modules.specialists.application.dto import CabinetView
from app.modules.specialists.application.ports import ProfileQuery
from app.modules.specialists.domain.completeness import completeness
from app.modules.specialists.domain.profile import ProfileKind
from app.platform.kernel.ids import UserId


class ProfileViews:
    def __init__(self, query: ProfileQuery, prices: PriceList) -> None:
        self._query, self._prices = query, prices

    async def of_user(self, user_id: UserId) -> CabinetView | None:
        view = await self._query.of_user(user_id)
        if view is None:
            return None
        prices = await self._prices.summary(view.id)
        if view.kind is ProfileKind.PRO and prices.items == 0:
            view = replace(view, missing=(*view.missing, "services"))
        full = completeness(
            kind=view.kind,
            category_ids=view.category_ids,
            headline=view.headline,
            about=view.about,
            languages=view.languages,
            work_modes=view.work_modes,
            area_ids=view.area_ids,
            price_items=prices.items,
            undescribed_prices=prices.without_description,
        )
        return CabinetView(profile=view, completeness=full)
