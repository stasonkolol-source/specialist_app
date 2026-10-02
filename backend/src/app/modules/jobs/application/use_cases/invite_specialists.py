"""Пригласить специалистов в свою заявку (POST /jobs/{id}/invites, S21 и S23; DEVELOPMENT_PLAN
5.6): только опубликованных — профиль скрыт, удалён или его автор под санкцией — 404
`invitee_not_found` («заблокированного пригласить нельзя»); свой профиль — 409. Заявка — своя и
открытая; приглашённых в ней не больше десяти (409 `job_invites_full`) — предел держит блокировка
строки заявки. Повторное приглашение — без ошибки и без второго уведомления. Новому приглашённому
— событие JobInvited: уведомление `job.invited` и `invite_sent` в аналитику.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.api import Action, IdentityApi
from app.modules.jobs.application.invitees import invitees
from app.modules.jobs.application.ports import JobInvites, JobRepository
from app.modules.jobs.domain.invite import MAX_INVITES, Invite
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.domain.policies import ensure_owner
from app.modules.jobs.errors import JobInvitesFullError, JobNotOpenError
from app.modules.specialists.api import SpecialistsApi
from app.platform.contracts.events.jobs import JobInvited
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class InviteSpecialistsCommand:
    actor_id: UserId
    job_id: JobId
    profile_ids: Sequence[UUID]


class InviteSpecialists:
    def __init__(
        self,
        uow: UnitOfWork,
        jobs: JobRepository,
        invites: JobInvites,
        specialists: SpecialistsApi,
        identity: IdentityApi,
        clock: Clock,
    ) -> None:
        self._uow, self._jobs, self._invites = uow, jobs, invites
        self._specialists, self._identity, self._clock = specialists, identity, clock

    async def __call__(self, cmd: InviteSpecialistsCommand) -> list[Invite]:
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        profiles = await invitees(
            self._specialists, self._identity, cmd.actor_id, list(dict.fromkeys(cmd.profile_ids))
        )
        now = self._clock.now()
        async with self._uow:
            job = await self._jobs.get_for_update(cmd.job_id)
            ensure_owner(job, cmd.actor_id)
            if not job.is_open:
                raise JobNotOpenError(job_id=job.id, job_status=job.status.value)
            existing = await self._invites.of_job(job.id)
            known = {invite.profile_id for invite in existing}
            fresh = [profile for profile in profiles if profile.id not in known]
            if len(existing) + len(fresh) > MAX_INVITES:
                raise JobInvitesFullError(limit=MAX_INVITES)
            added = []
            for profile in fresh:
                invite = Invite(
                    job_id=job.id,
                    profile_id=profile.id,
                    performer_id=profile.user_id,
                    invited_at=now,
                )
                await self._invites.add(invite)
                self._uow.add_event(
                    JobInvited(
                        job_id=job.id,
                        client_id=job.client_id,
                        profile_id=profile.id,
                        performer_id=profile.user_id,
                        direct=False,
                        occurred_at=now,
                    )
                )
                added.append(invite)
        return [*existing, *added]
