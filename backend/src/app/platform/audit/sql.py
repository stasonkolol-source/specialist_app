"""AuditLog на platform.audit_log в сессии текущего UoW; чтение журнала — SqlAuditReader."""

from sqlalchemy import Select, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.port import ActorKind, AuditEntry, AuditFilter, AuditRecord
from app.platform.db.platform_tables import audit_log
from app.platform.db.port import UnitOfWork
from app.platform.db.query import SqlQuery, decode_cursor, encode_cursor
from app.platform.kernel.pagination import Page, PageRequest


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


class SqlAuditReader(SqlQuery):
    """Журнал для Admin API: keyset по id (identity-колонка растёт вместе со временем записи)."""

    async def records(self, query: AuditFilter, page: PageRequest) -> Page[AuditRecord]:
        c = audit_log.c
        stmt = _filtered(select(audit_log), query).order_by(c.id.desc()).limit(page.limit + 1)
        if page.cursor is not None:
            (last_id,) = decode_cursor(page.cursor, (int,))
            stmt = stmt.where(c.id < last_id)
        rows = await self._fetch(stmt)
        items = tuple(
            AuditRecord(
                id=row["id"],
                action=row["action"],
                actor_kind=ActorKind(row["actor_kind"]),
                actor_id=row["actor_id"],
                entity_type=row["entity_type"],
                entity_id=row["entity_id"],
                changes=row["changes"],
                ip=str(row["ip"]) if row["ip"] is not None else None,
                created_at=row["created_at"],
            )
            for row in rows[: page.limit]
        )
        more = len(rows) > page.limit
        return Page(items=items, next_cursor=encode_cursor(items[-1].id) if more else None)


def _filtered(stmt: Select[tuple[object, ...]], query: AuditFilter) -> Select[tuple[object, ...]]:
    c = audit_log.c
    if query.action:
        prefix = query.action.rstrip(".")
        stmt = stmt.where(
            or_(c.action == prefix, c.action.startswith(f"{prefix}.", autoescape=True))
        )
    if query.actor_id is not None:
        stmt = stmt.where(c.actor_id == query.actor_id)
    if query.entity_type:
        stmt = stmt.where(c.entity_type == query.entity_type)
    if query.entity_id is not None:
        stmt = stmt.where(c.entity_id == query.entity_id)
    if query.since is not None:
        stmt = stmt.where(c.created_at >= query.since)
    if query.until is not None:
        stmt = stmt.where(c.created_at < query.until)
    return stmt
