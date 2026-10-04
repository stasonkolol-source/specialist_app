"""Адаптер цели «отклик» (план 5.4): фасад jobs для конвейера модерации.

Клиент видит отклик, когда проверка пройдена (§7.9): чистый текст — сразу после автопроверки,
флаг или неуверенный классификатор — после решения модератора (P2), нарушение скрывает отклик и
освобождает его место на заявке. Проверяется сообщение клиенту и «когда смогу».
"""

from uuid import UUID

from app.modules.jobs.api import JobsApi
from app.modules.moderation.application.ports import ModerationTarget, TargetContent
from app.platform.ai.port import ContentKind


class ResponseTarget(ModerationTarget):
    def __init__(self, jobs: JobsApi) -> None:
        self._jobs = jobs

    async def content(self, entity_id: UUID) -> TargetContent | None:
        response = await self._jobs.response_for_review(entity_id)
        if response is None:
            return None
        return TargetContent(
            author_id=response.performer_id,
            kind=ContentKind.RESPONSE,
            text=response.text,
            version=response.revision,
        )

    async def publish(
        self,
        entity_id: UUID,
        *,
        version: int | None = None,
        auto: bool = False,  # noqa: ARG002 — публикуется только ждущая проверки версия
    ) -> None:
        await self._jobs.approve_response(entity_id, version=version)

    async def hide(self, entity_id: UUID, *, reason_code: str) -> None:
        await self._jobs.reject_response(entity_id, reason_code=reason_code)
