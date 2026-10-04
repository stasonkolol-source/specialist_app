"""Работа в портфолио (S37, POST /me/profile/portfolio): загруженный файл пользователя с
назначением portfolio становится работой в конце списка. Лимит — 60 фото и 6 роликов на
профиль; профиль блокируется строкой, поэтому параллельные загрузки лимит не обходят. Повтор
того же файла возвращает ту же работу. Новая работа ждёт проверки (план 6.7): её видит только
владелец, пока модерация не проверит подпись и фото (ModerationRequested в той же транзакции)."""

from collections import Counter
from dataclasses import dataclass

from app.modules.media.api import MediaApi
from app.modules.specialists.application.ports import PortfolioRepository, ProfileRepository
from app.modules.specialists.application.profiles import own_profile, request_work_review
from app.modules.specialists.domain.portfolio import PortfolioItem, WorkKind, ensure_room
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import MediaId, UserId

PORTFOLIO_PURPOSE = "portfolio"


@dataclass(frozen=True, slots=True, kw_only=True)
class AddPortfolioWorkCommand:
    actor_id: UserId
    media_id: MediaId
    caption: str | None = None


class AddPortfolioWork:
    def __init__(
        self,
        uow: UnitOfWork,
        profiles: ProfileRepository,
        portfolio: PortfolioRepository,
        media: MediaApi,
        clock: Clock,
    ) -> None:
        self._uow, self._profiles, self._portfolio = uow, profiles, portfolio
        self._media, self._clock = media, clock

    async def __call__(self, cmd: AddPortfolioWorkCommand) -> PortfolioItem:
        async with self._uow:
            profile = await own_profile(self._profiles, cmd.actor_id)
            profile.ensure_editable()
            file = await self._media.owned(cmd.actor_id, cmd.media_id, purpose=PORTFOLIO_PURPOSE)
            items = await self._portfolio.list_for_update(profile.id)
            same = next((item for item in items if item.media_id == cmd.media_id), None)
            if same is not None:
                return same
            kind = WorkKind(file.kind)
            ensure_room(kind, Counter(item.kind for item in items))
            now = self._clock.now()
            item = PortfolioItem.add(
                profile_id=profile.id,
                media_id=cmd.media_id,
                kind=kind,
                caption=cmd.caption,
                position=len(items),
                now=now,
            )
            await self._portfolio.add(item)
            request_work_review(self._uow, item, cmd.actor_id, now=now)
        return item
