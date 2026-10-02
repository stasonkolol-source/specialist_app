"""Приглашения в заявку и прямые запросы (S21, S23, S08; DEVELOPMENT_PLAN 5.6): строка на пару
«заявка — профиль». Предел на заявку проверяет use case под блокировкой строки заявки."""

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.domain.invite import Invite
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.infrastructure.models import InviteRow
from app.platform.db.port import UnitOfWork
from app.platform.db.query import SqlQuery
from app.platform.kernel.ids import UserId

_I = InviteRow.__table__.c


class SqlJobInvites(SqlQuery):
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        super().__init__(session)
        self._uow = uow

    async def of_job(self, job_id: JobId) -> list[Invite]:
        rows = await self._fetch(
            select(_I.job_id, _I.profile_id, _I.performer_id, _I.invited_at)
            .where(_I.job_id == job_id)
            .order_by(_I.invited_at, _I.profile_id)
        )
        return [
            Invite(
                job_id=JobId(row["job_id"]),
                profile_id=row["profile_id"],
                performer_id=UserId(row["performer_id"]),
                invited_at=row["invited_at"],
            )
            for row in rows
        ]

    async def add(self, invite: Invite) -> None:
        self._uow.require_active()
        await self._session.execute(
            insert(InviteRow)
            .values(
                job_id=invite.job_id,
                profile_id=invite.profile_id,
                performer_id=invite.performer_id,
                invited_at=invite.invited_at,
            )
            .on_conflict_do_nothing(index_elements=["job_id", "profile_id"])
        )

    async def forget(self, performer_id: UserId) -> None:
        self._uow.require_active()
        await self._session.execute(delete(InviteRow).where(_I.performer_id == performer_id))
