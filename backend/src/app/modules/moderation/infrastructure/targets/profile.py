"""Адаптер цели «профиль исполнителя» (план 2.8a): фасад specialists для конвейера модерации.

Новый профиль и переход в «Специалист» всегда проверяет человек (`always_review`, §14.1);
правка опубликованного — пост-модерация. Риск — самый строгий из категорий профиля.
"""

from uuid import UUID

from app.modules.moderation.application.ports import ModerationTarget, TargetContent
from app.modules.specialists.api import SpecialistsApi
from app.platform.ai.port import ContentKind


class ProfileTarget(ModerationTarget):
    def __init__(self, specialists: SpecialistsApi) -> None:
        self._specialists = specialists

    async def content(self, entity_id: UUID) -> TargetContent | None:
        profile = await self._specialists.profile_for_review(entity_id)
        if profile is None:
            return None
        return TargetContent(
            author_id=profile.user_id,
            kind=ContentKind.PROFILE,
            text=profile.text,
            version=profile.version,
            always_review=profile.first_review,
            risk_level=profile.risk_level,
        )

    async def publish(self, entity_id: UUID, *, version: int | None = None) -> None:
        await self._specialists.approve_profile(entity_id, version=version)

    async def hide(self, entity_id: UUID, *, reason_code: str) -> None:
        await self._specialists.reject_profile(entity_id, reason_code=reason_code)
