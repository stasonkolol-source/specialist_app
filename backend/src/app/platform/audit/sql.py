"""AuditLog на platform.audit_log в сессии текущего UoW."""

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.port import AuditEntry
from app.platform.db.platform_tables import audit_log
from app.platform.db.port import UnitOfWork


class SqlAuditLog:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def record(self, entry: AuditEntry) -> None:
        self._uow.require_active()
        await self._session.execute(
            insert(audit_log).values(
                actor_id=entry.actor_id,
                actor_kind=entry.actor_kind.value,
                action=entry.action,
                entity_type=entry.entity_type,
                entity_id=entry.entity_id,
                changes=dict(entry.changes) if entry.changes is not None else None,
                ip=entry.ip,
            )
        )
