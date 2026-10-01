"""Свой профиль для кабинета: запрос плюс прайс — «чего не хватает» как при отправке, полнота
профиля (S33) и фото профиля."""

from dataclasses import replace

from app.modules.media.api import MediaApi
from app.modules.specialists.api import PriceList
from app.modules.specialists.application.dto import CabinetView
from app.modules.specialists.application.ports import PortfolioQuery, ProfileQuery
from app.modules.specialists.domain.completeness import completeness
from app.modules.specialists.domain.profile import ProfileKind
from app.platform.kernel.ids import UserId


class ProfileViews:
    def __init__(
        self,
        query: ProfileQuery,
        prices: PriceList,
        portfolio: PortfolioQuery,
        media: MediaApi,
    ) -> None:
        self._query, self._prices, self._portfolio, self._media = query, prices, portfolio, media

    async def of_user(self, user_id: UserId) -> CabinetView | None:
        view = await self._query.of_user(user_id)
        if view is None:
            return None
        prices = await self._prices.summary(view.id)
        if view.kind is ProfileKind.PRO and prices.items == 0:
            view = replace(view, missing=(*view.missing, "services"))
        avatar = None
        if view.avatar_media_id is not None:
            avatar = (await self._media.refs([view.avatar_media_id])).get(view.avatar_media_id)
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
            works=await self._portfolio.count(view.id),
            has_avatar=avatar is not None,
        )
        return CabinetView(profile=view, completeness=full, avatar=avatar)
