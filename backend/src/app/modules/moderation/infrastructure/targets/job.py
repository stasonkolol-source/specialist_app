"""Адаптер цели «заявка» (план 5.1): фасад jobs для конвейера модерации.

Чистая заявка публикуется сразу (§7.9), флаг, неуверенный классификатор или категория с
риском `≥ 1` — в очередь P2. Отказ: ждавшая проверки — «отклонена» (клиент исправит),
опубликованная — «снята». Фото проверяются вместе с текстом.
"""

from uuid import UUID

from app.modules.jobs.api import JobsApi
from app.modules.moderation.application.ports import ModerationTarget, TargetContent
from app.platform.ai.port import ContentKind


class JobTarget(ModerationTarget):
    def __init__(self, jobs: JobsApi) -> None:
        self._jobs = jobs

    async def content(self, entity_id: UUID) -> TargetContent | None:
        job = await self._jobs.job_for_review(entity_id)
        if job is None:
            return None
        return TargetContent(
            author_id=job.client_id,
            kind=ContentKind.JOB,
            text=job.text,
            media_ids=job.media_ids,
            version=job.version,
            risk_level=job.risk_level,
        )

    async def publish(
        self,
        entity_id: UUID,
        *,
        version: int | None = None,
        auto: bool = False,  # noqa: ARG002 — публикуется только ждущая проверки версия
    ) -> None:
        await self._jobs.approve_job(entity_id, version=version)

    async def hide(self, entity_id: UUID, *, reason_code: str) -> None:
        await self._jobs.reject_job(entity_id, reason_code=reason_code)
