"""Удаление аккаунта в PostgreSQL (ARCHITECTURE §7.10): запросы с grace-периодом и хэши
способов входа удалённых аккаунтов."""

from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.application.ports import DueCursor
from app.modules.identity.domain.deletion import DeletionRequest, DeletionRequestId, HashKind
from app.modules.identity.errors import ConcurrentDeletionRequestError
from app.modules.identity.infrastructure.models import DeletedIdentityHashRow, DeletionRequestRow
from app.platform.db.constraints import ConstraintErrors, raise_domain_error
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId

DELETION_CONSTRAINTS: ConstraintErrors = {
    "uq_deletion_requests_user_id_active": ConcurrentDeletionRequestError,
}

_ACTIVE = (DeletionRequestRow.cancelled_at.is_(None), DeletionRequestRow.completed_at.is_(None))


class SqlDeletionRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def active_for_update(self, user_id: UserId) -> DeletionRequest | None:
        self._uow.require_active()
        stmt = (
            select(DeletionRequestRow)
            .where(DeletionRequestRow.user_id == user_id, *_ACTIVE)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        request = _to_domain(row)
        self._uow.track(request)
        return request

    async def due(self, now: datetime, *, after: DueCursor | None, limit: int) -> list[DueCursor]:
        position = tuple_(DeletionRequestRow.execute_after, DeletionRequestRow.user_id)
        stmt = (
            select(DeletionRequestRow.execute_after, DeletionRequestRow.user_id)
            .where(DeletionRequestRow.execute_after <= now, *_ACTIVE)
            .order_by(DeletionRequestRow.execute_after, DeletionRequestRow.user_id)
            .limit(limit)
        )
        if after is not None:
            stmt = stmt.where(position > tuple_(*after))
        rows = (await self._session.execute(stmt)).all()
        return [(execute_after, UserId(user_id)) for execute_after, user_id in rows]

    async def add(self, request: DeletionRequest) -> None:
        self._uow.require_active()
        row = DeletionRequestRow(id=request.id)
        _apply(request, row)
        self._session.add(row)
        await self._flush()
        self._uow.track(request)

    async def save(self, request: DeletionRequest) -> None:
        self._uow.require_active()
        row = await self._session.get(DeletionRequestRow, request.id)
        if row is None:
            # строку создаёт add, а удалить запрос нельзя: такого не бывает
            raise LookupError(f"deletion request {request.id} is gone")
        _apply(request, row)
        await self._flush()
        self._uow.track(request)

    async def _flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as err:
            raise_domain_error(err, DELETION_CONSTRAINTS)


class SqlDeletedIdentities:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def remember(
        self,
        hashes: Mapping[bytes, HashKind],
        *,
        had_sanctions: bool,
        deleted_at: datetime,
        purge_after: datetime,
    ) -> None:
        if not hashes:
            return
        rows = [
            {
                "hash": digest,
                "kind": kind,
                "had_sanctions": had_sanctions,
                "deleted_at": deleted_at,
                "purge_after": purge_after,
            }
            for digest, kind in hashes.items()
        ]
        stmt = insert(DeletedIdentityHashRow).values(rows)
        # тот же Telegram удалял аккаунт уже не раз: срок — от последнего удаления, санкции
        # прежних аккаунтов не забываются
        stmt = stmt.on_conflict_do_update(
            index_elements=[DeletedIdentityHashRow.hash],
            set_={
                "deleted_at": stmt.excluded.deleted_at,
                "purge_after": stmt.excluded.purge_after,
                "had_sanctions": DeletedIdentityHashRow.had_sanctions | stmt.excluded.had_sanctions,
            },
        )
        await self._session.execute(stmt)

    async def find(self, digest: bytes, now: datetime) -> bool | None:
        stmt = select(DeletedIdentityHashRow.had_sanctions).where(
            DeletedIdentityHashRow.hash == digest, DeletedIdentityHashRow.purge_after > now
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def purge(self, now: datetime, *, limit: int) -> int:
        due = (
            select(DeletedIdentityHashRow.hash)
            .where(DeletedIdentityHashRow.purge_after <= now)
            .limit(limit)
        )
        result = await self._session.execute(
            delete(DeletedIdentityHashRow)
            .where(DeletedIdentityHashRow.hash.in_(due.scalar_subquery()))
            .returning(DeletedIdentityHashRow.hash)
        )
        return len(result.all())


def _to_domain(row: DeletionRequestRow) -> DeletionRequest:
    return DeletionRequest(
        id=DeletionRequestId(row.id),
        user_id=UserId(row.user_id),
        source=row.source,
        requested_at=row.requested_at,
        execute_after=row.execute_after,
        cancelled_at=row.cancelled_at,
        completed_at=row.completed_at,
    )


def _apply(request: DeletionRequest, row: DeletionRequestRow) -> None:
    row.user_id = request.user_id
    row.source = request.source
    row.requested_at = request.requested_at
    row.execute_after = request.execute_after
    row.cancelled_at = request.cancelled_at
    row.completed_at = request.completed_at


__all__: Sequence[str] = ("SqlDeletedIdentities", "SqlDeletionRepository")
