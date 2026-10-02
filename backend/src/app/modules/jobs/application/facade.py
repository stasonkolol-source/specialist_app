"""Реализация JobsApi (ADR-0020 §6): заявка для конвейера модерации, публикация и отказ."""

from typing import Final
from uuid import UUID

from app.modules.catalog.api import CatalogApi
from app.modules.jobs.api import JobForReview, JobsApi
from app.modules.jobs.application.ports import JobRepository
from app.modules.jobs.domain.job import JobId, JobStatus
from app.modules.jobs.errors import JobNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock

REVIEWABLE: Final = frozenset({JobStatus.PENDING_MODERATION, JobStatus.PUBLISHED})


class JobsFacade(JobsApi):
    def __init__(
        self, uow: UnitOfWork, jobs: JobRepository, catalog: CatalogApi, clock: Clock
    ) -> None:
        self._uow, self._jobs, self._catalog, self._clock = uow, jobs, catalog, clock

    async def job_for_review(self, job_id: UUID) -> JobForReview | None:
        async with self._uow:
            try:
                job = await self._jobs.get_for_update(JobId(job_id))
            except JobNotFoundError:
                return None
        if job.status not in REVIEWABLE:
            return None
        category = await self._catalog.category(job.content.category_id)
        return JobForReview(
            client_id=job.client_id,
            text=f"{job.content.title}\n\n{job.content.description}".strip(),
            version=job.version,
            media_ids=job.content.media_ids,
            risk_level=int(category.risk_level) if category is not None else 0,
        )

    async def approve_job(self, job_id: UUID, *, version: int | None) -> None:
        self._uow.require_active()
        try:
            job = await self._jobs.get_for_update(JobId(job_id))
        except JobNotFoundError:
            return
        if job.approve(version=version, now=self._clock.now()):
            await self._jobs.save(job)

    async def reject_job(self, job_id: UUID, *, reason_code: str) -> None:
        self._uow.require_active()
        try:
            job = await self._jobs.get_for_update(JobId(job_id))
        except JobNotFoundError:
            return
        if job.reject(reason_code=reason_code, now=self._clock.now()):
            await self._jobs.save(job)
