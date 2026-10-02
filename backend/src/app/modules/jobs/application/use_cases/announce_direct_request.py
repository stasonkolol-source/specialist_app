"""Прямой запрос опубликован (JobPublished с `direct`, DEVELOPMENT_PLAN 5.6): приглашённому —
событие JobInvited (уведомление `job.invited`, `direct_request_sent` в аналитику).
Переопубликация после правки или продления повторно не зовёт: специалист уже знает о запросе.
"""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobInvites, JobQueries
from app.modules.jobs.domain.job import JobId, JobStatus
from app.platform.contracts.events.jobs import JobInvited
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock


@dataclass(frozen=True, slots=True, kw_only=True)
class AnnounceDirectRequestCommand:
    job_id: JobId


class AnnounceDirectRequest:
    def __init__(
        self, uow: UnitOfWork, queries: JobQueries, invites: JobInvites, clock: Clock
    ) -> None:
        self._uow, self._queries, self._invites, self._clock = uow, queries, invites, clock

    async def __call__(self, cmd: AnnounceDirectRequestCommand) -> int:
        """Сколько специалистов позвали; заявку уже закрыли или удалили — никого."""
        job = await self._queries.view(cmd.job_id)
        if job is None or job.status is not JobStatus.PUBLISHED:
            return 0
        now = self._clock.now()
        async with self._uow:
            invites = await self._invites.of_job(job.id)
            for invite in invites:
                self._uow.add_event(
                    JobInvited(
                        job_id=job.id,
                        client_id=job.client_id,
                        profile_id=invite.profile_id,
                        performer_id=invite.performer_id,
                        direct=True,
                        occurred_at=now,
                    )
                )
        return len(invites)
