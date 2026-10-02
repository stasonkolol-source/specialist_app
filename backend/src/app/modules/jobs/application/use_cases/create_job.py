"""Создать заявку (POST /jobs, DEVELOPMENT_PLAN 5.1): сразу на проверку — черновик живёт только
на клиенте (5.2), `POST /jobs/{id}/submit` из §8.5 не нужен. Сначала санкции и согласия, потом
справочники и фото, потом лимиты новичка (§13.3): уровни 0–1 — не больше трёх активных и пяти
новых в сутки, проверенные — двадцать в сутки. Квота тратится последней: отказ по данным её не
съедает.

Прямой запрос специалисту (POST /specialists/{id}/requests, S08 и S09; 5.6) — та же заявка с
`visibility = direct` и приглашением этого профиля: её видят только клиент и он, модерация — та
же. Специалист узнаёт о запросе после публикации (AnnounceDirectRequest).
"""

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.identity.api import Action, IdentityApi
from app.modules.jobs.application.content import ContentBuilder, JobDraft
from app.modules.jobs.application.invitees import invitees
from app.modules.jobs.application.ports import JobInvites, JobQueries, JobQuota, JobRepository
from app.modules.jobs.application.review import request_review
from app.modules.jobs.domain.invite import Invite
from app.modules.jobs.domain.job import Job, JobId, Visibility
from app.modules.jobs.errors import ActiveJobsLimitError
from app.modules.specialists.api import SpecialistsApi
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
    direct_profile_id: UUID | None = None
    """Прямой запрос этому профилю: заявку видит только он."""


class CreateJob:
    def __init__(
        self,
        uow: UnitOfWork,
        jobs: JobRepository,
        queries: JobQueries,
        quota: JobQuota,
        builder: ContentBuilder,
        invites: JobInvites,
        identity: IdentityApi,
        specialists: SpecialistsApi,
        clock: Clock,
    ) -> None:
        self._uow, self._jobs, self._queries, self._quota = uow, jobs, queries, quota
        self._builder, self._invites, self._clock = builder, invites, clock
        self._identity, self._specialists = identity, specialists

    async def __call__(self, cmd: CreateJobCommand) -> JobId:
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        direct = None
        if cmd.direct_profile_id is not None:
            (direct,) = await invitees(
                self._specialists, self._identity, cmd.actor_id, [cmd.direct_profile_id]
            )
        job_id = JobId(new_id())
        built = await self._builder.build(job_id, cmd.actor_id, cmd.draft)
        trusted = cmd.trust_level >= TRUSTED_LEVEL
        if not trusted and await self._queries.count_active(cmd.actor_id) >= MAX_ACTIVE:
            raise ActiveJobsLimitError(retry_after=ACTIVE_RETRY_AFTER, limit=MAX_ACTIVE)
        await self._quota.take(cmd.actor_id, trusted=trusted)
        now = self._clock.now()
        job = Job.submit(
            job_id=job_id,
            client_id=cmd.actor_id,
            content=built.content,
            max_responses=built.max_responses,
            visibility=Visibility.PUBLIC if direct is None else Visibility.DIRECT,
            source=cmd.source,
            now=now,
        )
        async with self._uow:
            await self._jobs.add(job)
            if direct is not None:
                invite = Invite(
                    job_id=job.id, profile_id=direct.id, performer_id=direct.user_id, invited_at=now
                )
                await self._invites.add(invite)
            request_review(self._uow, job, edit=False)
        return job.id
