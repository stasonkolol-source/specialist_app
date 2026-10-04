"""Адаптеры целей «отзыв» и «ответ на отзыв» (план 7.2): фасад reviews для конвейера модерации.

Отзыв виден на карточке специалиста, когда проверка пройдена (ARCHITECTURE §7.9): чистый текст
(или одна оценка без текста) — сразу после автопроверки, флаг — после модератора, нарушение
снимает отзыв. «Отзыв до платформы» (7.6а) модератор проверяет всегда (`always_review`,
ADR-0016). Ответ исполнителя проверяется так же, но отдельно: нарушение в ответе скрывает
только ответ, отзыв клиента остаётся.
"""

from uuid import UUID

from app.modules.moderation.application.ports import ModerationTarget, TargetContent
from app.modules.reviews.api import ReviewsApi
from app.platform.ai.port import ContentKind


class ReviewTarget(ModerationTarget):
    def __init__(self, reviews: ReviewsApi) -> None:
        self._reviews = reviews

    async def content(self, entity_id: UUID) -> TargetContent | None:
        review = await self._reviews.review_for_check(entity_id)
        if review is None:
            return None
        return TargetContent(
            author_id=review.author_id,
            kind=ContentKind.REVIEW,
            text=review.text,
            always_review=review.always_review,
        )

    async def publish(
        self,
        entity_id: UUID,
        *,
        version: int | None = None,  # noqa: ARG002 — отзыв не редактируется
    ) -> None:
        await self._reviews.approve_review(entity_id)

    async def hide(self, entity_id: UUID, *, reason_code: str) -> None:
        await self._reviews.reject_review(entity_id, reason_code=reason_code)


class ReviewReplyTarget(ModerationTarget):
    def __init__(self, reviews: ReviewsApi) -> None:
        self._reviews = reviews

    async def content(self, entity_id: UUID) -> TargetContent | None:
        reply = await self._reviews.reply_for_check(entity_id)
        if reply is None:
            return None
        return TargetContent(
            author_id=reply.author_id,
            kind=ContentKind.REVIEW,
            text=reply.text,
        )

    async def publish(
        self,
        entity_id: UUID,
        *,
        version: int | None = None,  # noqa: ARG002 — ответ не редактируется
    ) -> None:
        await self._reviews.approve_reply(entity_id)

    async def hide(self, entity_id: UUID, *, reason_code: str) -> None:
        await self._reviews.reject_reply(entity_id, reason_code=reason_code)
