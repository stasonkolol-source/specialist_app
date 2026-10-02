"""Чтение identity для фасада и use cases (ADR-0020 §5)."""

from datetime import datetime

from sqlalchemy import or_, select

from app.modules.identity.api import TelegramUserView, UserSummary
from app.modules.identity.application.dto import MeView
from app.modules.identity.domain.consent import Consent
from app.modules.identity.domain.restriction import Restriction
from app.modules.identity.domain.user import AuthProvider, UserStatus
from app.modules.identity.infrastructure.models import (
    AuthIdentityRow,
    ConsentRow,
    DeletionRequestRow,
    RestrictionRow,
    UserRoleRow,
    UserRow,
)
from app.platform.db.query import SqlQuery
from app.platform.kernel.ids import CityId, UserId
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

    async def me(self, user_id: UserId) -> MeView | None:
        u, d = UserRow.__table__.c, DeletionRequestRow.__table__.c
        # ждущий запрос на удаление: S31 показывает дату и «Отменить»
        scheduled = (
            select(d.execute_after)
            .where(d.user_id == u.id, d.cancelled_at.is_(None), d.completed_at.is_(None))
            .scalar_subquery()
        )
        row = await self._fetch_one(
            select(
                u.id,
                u.display_name,
                u.ui_locale,
                u.trust_level,
                u.phone_verified_at,
                u.created_at,
                u.version,
                u.home_city_id,
                u.intent,
                scheduled.label("deletion_scheduled_at"),
            ).where(u.id == user_id, u.status == UserStatus.ACTIVE)
        )
        if row is None:
            return None
        return MeView(
            id=UserId(row["id"]),
            display_name=row["display_name"],
            ui_locale=row["ui_locale"],
            trust_level=row["trust_level"],
            phone_verified=row["phone_verified_at"] is not None,
            created_at=row["created_at"],
            version=row["version"],
            home_city_id=CityId(row["home_city_id"]) if row["home_city_id"] is not None else None,
            intent=row["intent"],
            deletion_scheduled_at=row["deletion_scheduled_at"],
        )

    async def by_telegram(self, telegram_id: int) -> TelegramUserView | None:
        u, i = UserRow.__table__.c, AuthIdentityRow.__table__.c
        row = await self._fetch_one(
            select(u.id, u.display_name, u.ui_locale, u.trust_level)
            .join(AuthIdentityRow.__table__, i.user_id == u.id)
            .where(
                i.provider == AuthProvider.TELEGRAM,
                i.subject == str(telegram_id),
                u.status == UserStatus.ACTIVE,
            )
        )
        if row is None:
            return None
        return TelegramUserView(
            id=UserId(row["id"]),
            display_name=row["display_name"],
            ui_locale=row["ui_locale"],
            trust_level=row["trust_level"],
        )

    async def telegram_chat_id(self, user_id: UserId) -> int | None:
        u, i = UserRow.__table__.c, AuthIdentityRow.__table__.c
        row = await self._fetch_one(
            select(i.subject)
            .join(UserRow.__table__, i.user_id == u.id)
            .where(
                i.user_id == user_id,
                i.provider == AuthProvider.TELEGRAM,
                u.status == UserStatus.ACTIVE,
            )
            .order_by(i.created_at)
            .limit(1)
        )
        return int(row["subject"]) if row is not None else None

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

    async def consents(self, user_id: UserId) -> list[Consent]:
        c = ConsentRow.__table__.c
        rows = await self._fetch(
            select(c.document, c.version, c.granted_at)
            .where(c.user_id == user_id, c.withdrawn_at.is_(None))
            .order_by(c.granted_at)
        )
        return [
            Consent(document=row["document"], version=row["version"], granted_at=row["granted_at"])
            for row in rows
        ]
