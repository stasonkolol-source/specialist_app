"""Правка заявки владельцем (PATCH /jobs/{id}, If-Match → 412): то же, что при создании, целиком.
Отклонённая после правки — снова на проверку; существенная правка опубликованной (текст, услуга,
бюджет, фото) — тоже (§7.9). Чужая — 404. If-Match сверяет редакцию содержимого (`Job.revision`):
автопубликация после прошлой правки её не меняет, и следующая правка не получает ложный 412."""

from dataclasses import dataclass

from app.modules.identity.api import Action, IdentityApi
from app.modules.jobs.application.content import ContentBuilder, JobDraft
from app.modules.jobs.application.ports import JobRepository
from app.modules.jobs.application.review import request_review
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.domain.policies import ensure_owner
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class EditJobCommand:
    actor_id: UserId
    job_id: JobId
    draft: JobDraft
    expected_version: int | None = None


class EditJob:
    def __init__(
        self,
        uow: UnitOfWork,
        jobs: JobRepository,
        builder: ContentBuilder,
        identity: IdentityApi,
        clock: Clock,
    ) -> None:
        self._uow, self._jobs, self._builder = uow, jobs, builder
        self._identity, self._clock = identity, clock

    async def __call__(self, cmd: EditJobCommand) -> None:
        await self._identity.ensure_allowed(cmd.actor_id, Action.POST)
        built = await self._builder.build(cmd.job_id, cmd.actor_id, cmd.draft)
        async with self._uow:
            job = await self._jobs.get_for_update(cmd.job_id)
            ensure_owner(job, cmd.actor_id)
            job.ensure_revision(cmd.expected_version)
            review = job.edit(built.content, now=self._clock.now())
            await self._jobs.save(job)
            if review:
                request_review(self._uow, job, edit=True)
