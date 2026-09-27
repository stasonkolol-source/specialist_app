"""IdempotencyStore на platform.idempotency_keys (в транзакции текущего UoW)."""

import hmac
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.db.platform_tables import idempotency_keys as keys
from app.platform.db.port import UnitOfWork
from app.platform.idempotency.port import Reservation, ReservationStatus


class SqlIdempotencyStore:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def reserve(
        self, user_id: UUID, key: str, request_hash: bytes, *, not_before: datetime
    ) -> Reservation:
        self._uow.require_active()
        await self._session.execute(
            delete(keys).where(
                keys.c.user_id == user_id, keys.c.key == key, keys.c.created_at < not_before
            )
        )
        inserted = await self._session.execute(
            insert(keys)
            .values(user_id=user_id, key=key, request_hash=request_hash)
            .on_conflict_do_nothing()
            .returning(keys.c.key)
        )
        if inserted.first() is not None:
            return Reservation(status=ReservationStatus.RESERVED)
        row = (
            await self._session.execute(
                select(keys.c.request_hash, keys.c.status_code, keys.c.response)
                .where(keys.c.user_id == user_id, keys.c.key == key)
                .with_for_update()
            )
        ).one()
        if not hmac.compare_digest(row.request_hash, request_hash):
            return Reservation(status=ReservationStatus.MISMATCH)
        if row.status_code is None:
            return Reservation(status=ReservationStatus.IN_PROGRESS)
        return Reservation(
            status=ReservationStatus.COMPLETED, status_code=row.status_code, response=row.response
        )

    async def complete(self, user_id: UUID, key: str, status_code: int, response: object) -> None:
        self._uow.require_active()
        await self._session.execute(
            update(keys)
            .where(keys.c.user_id == user_id, keys.c.key == key)
            .values(status_code=status_code, response=response)
        )

    async def release(self, user_id: UUID, key: str) -> None:
        self._uow.require_active()
        await self._session.execute(
            delete(keys).where(
                and_(keys.c.user_id == user_id, keys.c.key == key, keys.c.status_code.is_(None))
            )
        )

    async def cleanup(self, *, before: datetime) -> int:
        self._uow.require_active()
        result = await self._session.execute(delete(keys).where(keys.c.created_at < before))
        return int(result.rowcount or 0)  # type: ignore[attr-defined]  # CursorResult у DML
