"""Адаптер цели «работа портфолио» (план 6.7): фасад specialists для конвейера модерации.

Новая работа ждёт проверки: публикуется, когда чисты и подпись (конвейер текста), и фото
(`moderation.check_image`). Пока фото не проверено или ждёт модератора, проверять подпись рано —
`content` пуст; итог фото снова запрашивает проверку работы (`SpecialistsApi.recheck_works`:
автопроверка фото и решение модератора по кейсу фото). Итог фото читается под блокировкой строки
файла: запись итога параллельно не проскочит между чтением и запросом повторной проверки.
Портфолио нового профиля (ещё не опубликованного) всегда проверяет человек (`always_review`,
§14.1, ADR-0016); правка подписи опубликованной работы — пост-модерация. Риск — самый строгий из
категорий профиля, как у профиля. Хранилище не нужно: решение модератора работает и в боте.
"""

from uuid import UUID

from app.modules.media.api import MediaModeration, ModerationVerdict
from app.modules.moderation.application.ports import ModerationTarget, TargetContent
from app.modules.specialists.api import SpecialistsApi
from app.platform.ai.port import ContentKind
from app.platform.db.port import UnitOfWork


class PortfolioTarget(ModerationTarget):
    def __init__(
        self, uow: UnitOfWork, specialists: SpecialistsApi, media: MediaModeration
    ) -> None:
        self._uow, self._specialists, self._media = uow, specialists, media

    async def content(self, entity_id: UUID) -> TargetContent | None:
        work = await self._specialists.work_for_review(entity_id)
        if work is None:
            return None
        if work.pending:
            async with self._uow:
                verdict = await self._media.verdict(work.media_id)
            if verdict is not ModerationVerdict.APPROVED:
                return None  # подпись проверим, когда фото пройдёт проверку
        return TargetContent(
            author_id=work.user_id,
            kind=ContentKind.PROFILE,  # подпись — часть профиля исполнителя
            text=work.caption or "",
            media_ids=(work.media_id,),
            always_review=work.pending and work.new_profile,
            risk_level=work.risk_level,
        )

    async def publish(
        self,
        entity_id: UUID,
        *,
        version: int | None = None,  # noqa: ARG002 — у работы версий нет
    ) -> None:
        await self._specialists.approve_work(entity_id)

    async def hide(self, entity_id: UUID, *, reason_code: str) -> None:  # noqa: ARG002
        await self._specialists.reject_work(entity_id)
