"""Адаптер цели «профиль исполнителя» (план 2.8a): фасад specialists для конвейера модерации.

Новый профиль и переход в «Специалист» всегда проверяет человек (`always_review`, §14.1);
правка опубликованного — пост-модерация. Риск — самый строгий из категорий профиля.

Текст проверки — имя, заголовок, «о себе» и видимый прайс (название, описание, единица позиции):
прайс клиент видит на S08–S09, контакт в нём прошёл бы мимо проверки (B3); правка прайса —
тоже пост-модерация профиля (подписчик PriceListChanged).
"""

from uuid import UUID

from app.modules.moderation.application.ports import ModerationTarget, TargetContent
from app.modules.pricing.api import PricingApi
from app.modules.specialists.api import SpecialistsApi
from app.platform.ai.port import ContentKind


class ProfileTarget(ModerationTarget):
    def __init__(self, specialists: SpecialistsApi, pricing: PricingApi) -> None:
        self._specialists, self._pricing = specialists, pricing

    async def content(self, entity_id: UUID) -> TargetContent | None:
        profile = await self._specialists.profile_for_review(entity_id)
        if profile is None:
            return None
        prices = await self._pricing.text_for_review(entity_id)
        return TargetContent(
            author_id=profile.user_id,
            kind=ContentKind.PROFILE,
            text="\n".join(part for part in (profile.text, prices) if part),
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
        await self._specialists.approve_profile(entity_id, version=version)

    async def hide(self, entity_id: UUID, *, reason_code: str) -> None:
        await self._specialists.reject_profile(entity_id, reason_code=reason_code)
