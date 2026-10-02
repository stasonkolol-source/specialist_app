"""Реализация JobsApi (ADR-0020 §6): заявка для конвейера модерации, публикация и отказ;
краткие сведения о сроке — для уведомлений клиенту."""

from typing import Final
from uuid import UUID

from app.modules.catalog.api import CatalogApi
from app.modules.jobs.api import JobBrief, JobForReview, JobsApi
from app.modules.jobs.application.ports import JobQueries, JobRepository
from app.modules.jobs.domain.job import MAX_EXTENSIONS, JobId, JobStatus
from app.modules.jobs.errors import JobNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock

REVIEWABLE: Final = frozenset({JobStatus.PENDING_MODERATION, JobStatus.PUBLISHED})


class JobsFacade(JobsApi):
    def __init__(
        self,
        uow: UnitOfWork,
        jobs: JobRepository,
        queries: JobQueries,
        catalog: CatalogApi,
        clock: Clock,
    ) -> None:
        self._uow, self._jobs, self._queries = uow, jobs, queries
        self._catalog, self._clock = catalog, clock

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

    async def job_brief(self, job_id: UUID) -> JobBrief | None:
        job = await self._queries.view(JobId(job_id))
        if job is None:
            return None
        return JobBrief(
            client_id=job.client_id,
            title=job.title,
            status=job.status.value,
            expires_at=job.expires_at,
            can_extend=job.extensions_count < MAX_EXTENSIONS,
        )
