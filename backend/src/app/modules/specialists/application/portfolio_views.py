"""Портфолио для кабинета S37: работы по порядку и как показать их файлы."""

from app.modules.media.api import MediaApi
from app.modules.specialists.application.dto import WorkView
from app.modules.specialists.application.ports import PortfolioQuery, ProfileQuery
from app.platform.kernel.ids import UserId


class PortfolioViews:
    def __init__(self, profiles: ProfileQuery, portfolio: PortfolioQuery, media: MediaApi) -> None:
        self._profiles, self._portfolio, self._media = profiles, portfolio, media

    async def of_user(self, user_id: UserId) -> list[WorkView] | None:
        """Работы своего профиля; None — профиля нет."""
        profile = await self._profiles.of_user(user_id)
        if profile is None:
            return None
        items = await self._portfolio.of_profile(profile.id)
        refs = await self._media.refs([item.media_id for item in items])
        return [
            WorkView(
                id=item.id,
                kind=item.kind,
                caption=item.caption,
                position=item.position,
                media=refs.get(item.media_id),
            )
            for item in items
        ]
