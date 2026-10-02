"""Кого клиент пригласил в свою заявку (GET /jobs/{id}/invites, S23; DEVELOPMENT_PLAN 5.6): по
порядку приглашения. Чужая заявка — 404."""

from dataclasses import dataclass

from app.modules.jobs.application.ports import JobInvites, JobQueries
from app.modules.jobs.domain.invite import Invite
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.errors import JobNotFoundError
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ListJobInvitesCommand:
    actor_id: UserId
    job_id: JobId


class ListJobInvites:
    def __init__(self, queries: JobQueries, invites: JobInvites) -> None:
        self._queries, self._invites = queries, invites

    async def __call__(self, cmd: ListJobInvitesCommand) -> list[Invite]:
        job = await self._queries.view(cmd.job_id)
        if job is None or job.client_id != cmd.actor_id:
            raise JobNotFoundError(job_id=cmd.job_id)
        return await self._invites.of_job(cmd.job_id)
