"""Свой профиль для кабинета: запрос плюс прайс — «чего не хватает» как при отправке, полнота
профиля (S33) и фото профиля. Работы и фото, чей файл не прошёл обработку, в полноту не идут:
показать их клиенту нечем."""

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
        works = await self._portfolio.of_profile(view.id)
        wanted = [work.media_id for work in works]
        if view.avatar_media_id is not None:
            wanted.append(view.avatar_media_id)
        refs = await self._media.refs(wanted) if wanted else {}
        avatar = refs.get(view.avatar_media_id) if view.avatar_media_id is not None else None
        shown = [work for work in works if (ref := refs.get(work.media_id)) and not ref.broken]
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
            works=len(shown),
            has_avatar=avatar is not None and not avatar.broken,
        )
        return CabinetView(profile=view, completeness=full, avatar=avatar)
