"""Адаптер цели «профиль исполнителя» (план 2.8a): фасад specialists для конвейера модерации.

Новый профиль и переход в «Специалист» всегда проверяет человек (`always_review`, §14.1);
правка опубликованного — пост-модерация. Риск — самый строгий из категорий профиля.

Текст проверки — имя, заголовок, «о себе» и видимый прайс (название, описание, единица позиции):
прайс клиент видит на S08–S09, контакт в нём прошёл бы мимо проверки (B3); правка прайса —
тоже пост-модерация профиля (подписчик PriceListChanged). У нового профиля в текст входят и
подписи работ, ждущих проверки, а их фото — доказательства кейса: модератор решает о профиле
целиком, и «Одобрить профиль» публикует эти работы, а их фото считает проверенными (B5, Q34).
Фото, которое скрыла проверка (P0) или ещё не проверенное, одобрение профиля не публикует: такая
работа ждёт своего решения.
"""

from uuid import UUID

from app.modules.media.api import MediaModeration, ModerationVerdict
from app.modules.moderation.application.ports import ModerationTarget, TargetContent
from app.modules.pricing.api import PricingApi
from app.modules.specialists.api import SpecialistsApi
from app.platform.ai.port import ContentKind

SEEN = frozenset({ModerationVerdict.APPROVED, ModerationVerdict.FLAGGED})
"""Итог фото, после которого модератор видел его в кейсе профиля: чистое или ждущее человека.
Ещё не проверенное (None) и скрытое (P0) одобрение профиля не публикует."""


class ProfileTarget(ModerationTarget):
    def __init__(
        self, specialists: SpecialistsApi, pricing: PricingApi, media: MediaModeration
    ) -> None:
        self._specialists, self._pricing, self._media = specialists, pricing, media

    async def content(self, entity_id: UUID) -> TargetContent | None:
        profile = await self._specialists.profile_for_review(entity_id)
        if profile is None:
            return None
        prices = await self._pricing.text_for_review(entity_id)
        return TargetContent(
            author_id=profile.user_id,
            kind=ContentKind.PROFILE,
            text="\n".join(part for part in (profile.text, prices) if part),
            media_ids=profile.media_ids,
            version=profile.version,
            always_review=profile.first_review,
            risk_level=profile.risk_level,
        )

    async def publish(
        self,
        entity_id: UUID,
        *,
        version: int | None = None,
        auto: bool = False,  # noqa: ARG002 — публикуется только ждущая проверки версия
    ) -> None:
        waiting = await self._specialists.waiting_works(entity_id)
        if not await self._specialists.approve_profile(entity_id, version=version):
            return
        for work in waiting:
            verdict = await self._media.verdict(work.media_id)
            if verdict not in SEEN:
                continue
            if verdict is not ModerationVerdict.APPROVED:
                await self._media.moderate(work.media_id, ModerationVerdict.APPROVED)
            await self._specialists.approve_work(work.id, version=work.revision)

    async def hide(self, entity_id: UUID, *, reason_code: str) -> None:
        await self._specialists.reject_profile(entity_id, reason_code=reason_code)
