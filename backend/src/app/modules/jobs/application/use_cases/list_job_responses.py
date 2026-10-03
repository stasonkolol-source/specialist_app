"""Отклики на свою заявку (GET /jobs/{id}/responses, S23; DEVELOPMENT_PLAN 5.4): только
владельцу — чужая заявка как несуществующая (404). Отклики, прошедшие проверку, по порядку, с
именем исполнителя и «Откликнулся первым»; отклики тех, с кем у клиента блокировка (4.7), — нет.
Действия клиента (просмотр, избранные, отказ, выбор) — шаги 5.6 и 6.1."""

from dataclasses import dataclass

from app.modules.identity.api import IdentityApi
from app.modules.jobs.application.ports import JobQueries
from app.modules.jobs.application.responses import OwnerResponse
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.errors import JobNotFoundError
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ListJobResponsesCommand:
    actor_id: UserId
    job_id: JobId


@dataclass(frozen=True, slots=True, kw_only=True)
class JobResponse:
    response: OwnerResponse
    performer_name: str
    """Имя исполнителя; аккаунт удалён — пусто."""


class ListJobResponses:
    def __init__(self, queries: JobQueries, identity: IdentityApi) -> None:
        self._queries, self._identity = queries, identity

    async def __call__(self, cmd: ListJobResponsesCommand) -> list[JobResponse]:
        job = await self._queries.view(cmd.job_id)
        if job is None or job.client_id != cmd.actor_id:
            raise JobNotFoundError(job_id=cmd.job_id)
        responses = await self._queries.job_responses(cmd.job_id)
        users = await self._identity.users(
            {response.performer_id for response in responses}, viewer_id=cmd.actor_id
        )
        listed = []
        for response in responses:
            user = users.get(response.performer_id)
            if user is not None and user.block is not None:
                continue
            name = user.display_name if user is not None and not user.is_deleted else ""
            listed.append(JobResponse(response=response, performer_name=name))
        return listed
