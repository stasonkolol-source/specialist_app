"""Откликнуться на заявку (POST /jobs/{id}/responses, S16; DEVELOPMENT_PLAN 5.4).

Сначала санкции и согласия, потом сообщение и цена. Лимит мест — под блокировкой строки заявки:
десять параллельных откликов на пять мест дадут ровно пять. Суточная квота (§13.3) тратится
последней — после всех проверок заявки, поэтому отказ «мест нет» её не съедает. Отклик от
профиля специалиста, если он опубликован; иначе — подработка. Текст сразу уходит на проверку:
клиент видит отклик, когда её пройдёт.
"""

from dataclasses import dataclass
from typing import Final

from app.modules.identity.api import Action, IdentityApi
from app.modules.jobs.application.ports import (
    JobQueries,
    JobRepository,
    ResponseQuota,
    ResponseTemplates,
)
from app.modules.jobs.application.review import request_response_review
from app.modules.jobs.application.visibility import visible_to
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.domain.response import Offer, ResponseId
from app.modules.jobs.domain.template import TemplateId
from app.modules.jobs.errors import (
    ActiveResponsesLimitError,
    JobNotFoundError,
    TemplateNotFoundError,
)
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.entitlements.port import ACTIVE_RESPONSES, Entitlements
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId, new_id

TRUSTED_LEVEL: Final = 2
"""«Проверенный» (§13.2): пятьдесят откликов в сутки вместо десяти."""
PUBLISHED_PROFILE: Final = "published"


@dataclass(frozen=True, slots=True, kw_only=True)
class RespondCommand:
    actor_id: UserId
    trust_level: int
    job_id: JobId
    offer: Offer
    template_id: TemplateId | None = None
    """Отклик из своего шаблона (S16, кнопка бота 5.7); чужой или удалённый — 404."""


class Respond:
    def __init__(
        self,
        uow: UnitOfWork,
        jobs: JobRepository,
        queries: JobQueries,
        quota: ResponseQuota,
        templates: ResponseTemplates,
        identity: IdentityApi,
        specialists: SpecialistsApi,
        entitlements: Entitlements,
        clock: Clock,
    ) -> None:
        self._uow, self._jobs, self._queries, self._quota = uow, jobs, queries, quota
        self._templates, self._identity, self._specialists = templates, identity, specialists
        self._entitlements, self._clock = entitlements, clock

    async def __call__(self, cmd: RespondCommand) -> tuple[JobId, ResponseId]:
        await self._identity.ensure_allowed(cmd.actor_id, Action.RESPOND)
        allowed = await self._entitlements.quota(cmd.actor_id, ACTIVE_RESPONSES)
        if (
            allowed is not None
            and await self._queries.count_active_responses(cmd.actor_id) >= allowed
        ):
            raise ActiveResponsesLimitError(limit=allowed)
        profile = await self._specialists.profile_of(cmd.actor_id)
        profile_id = profile.id if profile and profile.status == PUBLISHED_PROFILE else None
        now = self._clock.now()
        async with self._uow:
            if cmd.template_id is not None and not any(
                t.id == cmd.template_id for t in await self._templates.of_user(cmd.actor_id)
            ):
                raise TemplateNotFoundError(template_id=cmd.template_id)
            job = await self._jobs.get_for_update(cmd.job_id)
            if not await visible_to(self._queries, job, cmd.actor_id):
                raise JobNotFoundError(job_id=cmd.job_id)
            response = job.respond(
                response_id=ResponseId(new_id()),
                performer_id=cmd.actor_id,
                offer=cmd.offer,
                profile_id=profile_id,
                template_id=cmd.template_id,
                now=now,
            )
            await self._quota.take(cmd.actor_id, trusted=cmd.trust_level >= TRUSTED_LEVEL)
            await self._jobs.save(job)
            request_response_review(self._uow, response, edit=False)
        return job.id, response.id
