"""Создать заявку (POST /jobs, DEVELOPMENT_PLAN 5.1): сразу на проверку — черновик живёт только
на клиенте (5.2), `POST /jobs/{id}/submit` из §8.5 не нужен. Сначала санкции и согласия, потом
справочники и фото, потом лимиты новичка (§13.3): уровни 0–1 — не больше трёх активных и пяти
новых в сутки, проверенные — двадцать в сутки. Квота тратится последней: отказ по данным её не
съедает.
"""

from dataclasses import dataclass
from typing import Final

from app.modules.identity.api import Action, IdentityApi
from app.modules.jobs.application.content import ContentBuilder, JobDraft
from app.modules.jobs.application.ports import JobQueries, JobQuota, JobRepository
from app.modules.jobs.application.review import request_review
from app.modules.jobs.domain.job import Job, JobId, Visibility
from app.modules.jobs.errors import ActiveJobsLimitError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId, new_id

TRUSTED_LEVEL: Final = 2
"""«Проверенный» (§13.2): без лимита активных, двадцать новых в сутки."""
MAX_ACTIVE: Final = 3
ACTIVE_RETRY_AFTER: Final = 3600
"""Секунд до повтора при лимите активных: место освободит закрытие или проверка."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateJobCommand:
    actor_id: UserId
    trust_level: int
    draft: JobDraft
    source: str = "tma"


class CreateJob:
    def __init__(
        self,
        uow: UnitOfWork,
        jobs: JobRepository,
        queries: JobQueries,
        quota: JobQuota,
        builder: ContentBuilder,
        identity: IdentityApi,
        clock: Clock,
    ) -> None:
        self._uow, self._jobs, self._queries, self._quota = uow, jobs, queries, quota
        self._builder, self._identity, self._clock = builder, identity, clock

    async def __call__(self, cmd: CreateJobCommand) -> JobId:
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        job_id = JobId(new_id())
        built = await self._builder.build(job_id, cmd.actor_id, cmd.draft)
        trusted = cmd.trust_level >= TRUSTED_LEVEL
        if not trusted and await self._queries.count_active(cmd.actor_id) >= MAX_ACTIVE:
            raise ActiveJobsLimitError(retry_after=ACTIVE_RETRY_AFTER, limit=MAX_ACTIVE)
        await self._quota.take(cmd.actor_id, trusted=trusted)
        job = Job.submit(
            job_id=job_id,
            client_id=cmd.actor_id,
            content=built.content,
            max_responses=built.max_responses,
            visibility=Visibility.PUBLIC,
            source=cmd.source,
            now=self._clock.now(),
        )
        async with self._uow:
            await self._jobs.add(job)
            request_review(self._uow, job, edit=False)
        return job.id
