"""Видна ли заявка зрителю (ARCHITECTURE §13.1, DEVELOPMENT_PLAN 5.6): правило — в policies, а
приглашён ли зритель в прямой запрос, use case узнаёт запросом — только когда это важно."""

from typing import Protocol

from app.modules.jobs.application.ports import JobQueries
from app.modules.jobs.domain.job import JobId, JobStatus, Visibility
from app.modules.jobs.domain.policies import can_view, needs_invite
from app.platform.kernel.ids import UserId


class Viewable(Protocol):
    @property
    def id(self) -> JobId: ...

    @property
    def client_id(self) -> UserId: ...

    @property
    def status(self) -> JobStatus: ...

    @property
    def visibility(self) -> Visibility: ...


async def visible_to(queries: JobQueries, job: Viewable, viewer_id: UserId | None) -> bool:
    invited = False
    if viewer_id is not None and needs_invite(
        client_id=job.client_id, visibility=job.visibility, viewer_id=viewer_id
    ):
        invited = await queries.is_invited(job.id, viewer_id)
    return can_view(
        client_id=job.client_id,
        status=job.status,
        viewer_id=viewer_id,
        visibility=job.visibility,
        invited=invited,
    )
