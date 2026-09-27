"""Чтение identity для фасада и use cases (ADR-0020 §5)."""

from datetime import datetime

from sqlalchemy import or_, select

from app.modules.identity.api import UserSummary
from app.modules.identity.domain.restriction import Restriction
from app.modules.identity.domain.user import UserStatus
from app.modules.identity.infrastructure.models import RestrictionRow, UserRoleRow, UserRow
from app.platform.db.query import SqlQuery
from app.platform.kernel.ids import UserId
from app.platform.kernel.principal import Role


class SqlIdentityQuery(SqlQuery):
    async def user_summary(self, user_id: UserId) -> UserSummary | None:
        u = UserRow.__table__.c
        row = await self._fetch_one(
            select(
                u.id,
                u.display_name,
                u.ui_locale,
                u.trust_level,
                u.phone_verified_at,
                u.status,
                u.created_at,
            ).where(u.id == user_id)
        )
        if row is None:
            return None
        return UserSummary(
            id=UserId(row["id"]),
            display_name=row["display_name"],
            ui_locale=row["ui_locale"],
            trust_level=row["trust_level"],
            phone_verified=row["phone_verified_at"] is not None,
            is_deleted=row["status"] == UserStatus.DELETED,
            created_at=row["created_at"],
        )

    async def roles(self, user_id: UserId) -> frozenset[Role]:
        r = UserRoleRow.__table__.c
        rows = await self._fetch(select(r.role).where(r.user_id == user_id))
        return frozenset(Role(row["role"]) for row in rows)

    async def restrictions(self, user_id: UserId, now: datetime) -> list[Restriction]:
        r = RestrictionRow.__table__.c
        rows = await self._fetch(
            select(r.kind, r.reason_code, r.starts_at, r.ends_at)
            .where(r.user_id == user_id, r.lifted_at.is_(None))
            .where(or_(r.ends_at.is_(None), r.ends_at > now))
        )
        return [
            Restriction(
                kind=row["kind"],
                reason_code=row["reason_code"],
                starts_at=row["starts_at"],
                ends_at=row["ends_at"],
            )
            for row in rows
        ]
