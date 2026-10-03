"""Чтение identity для фасада и use cases (ADR-0020 §5)."""

from collections.abc import Collection, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, RowMapping, and_, exists, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import aggregate_order_by

from app.modules.identity.api import BlockSide, TelegramUserView, UserSummary
from app.modules.identity.application.dto import LoginState, MeState, MeView
from app.modules.identity.domain.consent import Consent, ConsentDocument
from app.modules.identity.domain.restriction import Restriction, RestrictionKind
from app.modules.identity.domain.user import AuthProvider, Privacy, UserStatus
from app.modules.identity.infrastructure.models import (
    AuthIdentityRow,
    CompletedDealRow,
    ConsentRow,
    DeletionRequestRow,
    RestrictionRow,
    UserBlockRow,
    UserRoleRow,
    UserRow,
)
from app.platform.db.query import SqlQuery
from app.platform.kernel.ids import CityId, UserId
from app.platform.kernel.principal import Role


class SqlIdentityQuery(SqlQuery):
    async def user_summary(
        self, user_id: UserId, *, viewer_id: UserId | None = None
    ) -> UserSummary | None:
        stmt = _SUMMARY.where(UserRow.__table__.c.id == user_id)
        if viewer_id is not None:
            blocks = UserBlockRow.__table__.c
            stmt = stmt.add_columns(
                exists()
                .where(blocks.blocker_id == viewer_id, blocks.blocked_id == _U.id)
                .label("by_me"),
                exists()
                .where(blocks.blocker_id == _U.id, blocks.blocked_id == viewer_id)
                .label("by_them"),
            )
        row = await self._fetch_one(stmt)
        if row is None:
            return None
        summary = _summary(row)
        if viewer_id is None:
            return summary
        block = BlockSide.BY_ME if row["by_me"] else BlockSide.BY_THEM if row["by_them"] else None
        return replace(summary, block=block)

    async def user_summaries(self, user_ids: Collection[UserId]) -> dict[UserId, UserSummary]:
        if not user_ids:
            return {}
        rows = await self._fetch(_SUMMARY.where(UserRow.__table__.c.id.in_(list(user_ids))))
        return {summary.id: summary for summary in map(_summary, rows)}

    async def me(self, user_id: UserId) -> MeView | None:
        row = await self._fetch_one(_ME.where(_U.id == user_id, _U.status == UserStatus.ACTIVE))
        return _me(row) if row is not None else None

    async def me_state(self, user_id: UserId, now: datetime) -> MeState | None:
        """Профиль, санкции и согласия — одним запросом: GET /me и ответы правок S31 (было три
        отдельных чтения)."""
        row = await self._fetch_one(
            _ME.add_columns(
                _restrictions_json(_U.id, now).label("restrictions"),
                _consents_json(_U.id).label("consents"),
            ).where(_U.id == user_id, _U.status == UserStatus.ACTIVE)
        )
        if row is None:
            return None
        return MeState(
            me=_me(row),
            restrictions=[_restriction(item) for item in row["restrictions"] or ()],
            consents=[_consent(item) for item in row["consents"] or ()],
        )

    async def login_state(self, user_id: UserId) -> LoginState:
        r = UserRoleRow.__table__.c
        roles = func.array(select(r.role).where(r.user_id == user_id).scalar_subquery())
        [row] = await self._fetch(  # SELECT без FROM — ровно одна строка
            select(
                roles.label("roles"),
                _consents_json(user_id).label("consents"),
                _scheduled(user_id).label("deletion_scheduled_at"),
            )
        )
        return LoginState(
            roles=frozenset(Role(role) for role in row["roles"] or ()),
            consents=[_consent(item) for item in row["consents"] or ()],
            deletion_scheduled_at=row["deletion_scheduled_at"],
        )

    async def telegram_contacts(self, user_ids: Collection[UserId]) -> dict[UserId, str]:
        if not user_ids:
            return {}
        u, i = UserRow.__table__.c, AuthIdentityRow.__table__.c
        username = i.profile["username"].astext
        rows = await self._fetch(
            select(u.id, u.privacy, username.label("username"))
            .join(AuthIdentityRow.__table__, i.user_id == u.id)
            .where(
                u.id.in_(list(user_ids)),
                u.status == UserStatus.ACTIVE,
                i.provider == AuthProvider.TELEGRAM,
                username.is_not(None),
            )
        )
        return {
            UserId(row["id"]): f"@{row['username']}"
            for row in rows
            if Privacy.from_mapping(row["privacy"] or {}).show_telegram
        }

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

    async def completed_deals(self, user_id: UserId) -> int:
        row = await self._fetch_one(
            select(func.count().label("count")).where(CompletedDealRow.user_id == user_id)
        )
        return int(row["count"]) if row is not None else 0

    async def active_restrictions(
        self, user_ids: Collection[UserId], now: datetime
    ) -> dict[UserId, list[Restriction]]:
        """Неудалённые пользователи из списка и их неснятые санкции (действующие сейчас или
        позже) — одним запросом; удалённого и несуществующего нет в ответе."""
        u, r = UserRow.__table__.c, RestrictionRow.__table__.c
        in_force = and_(
            r.user_id == u.id, r.lifted_at.is_(None), or_(r.ends_at.is_(None), r.ends_at > now)
        )
        rows = await self._fetch(
            select(u.id, r.kind, r.reason_code, r.starts_at, r.ends_at)
            .select_from(UserRow.__table__)
            .outerjoin(RestrictionRow.__table__, in_force)
            .where(u.id.in_(list(user_ids)), u.status == UserStatus.ACTIVE)
        )
        found: dict[UserId, list[Restriction]] = {}
        for row in rows:
            restrictions = found.setdefault(UserId(row["id"]), [])
            if row["kind"] is not None:
                restrictions.append(
                    Restriction(
                        kind=row["kind"],
                        reason_code=row["reason_code"],
                        starts_at=row["starts_at"],
                        ends_at=row["ends_at"],
                    )
                )
        return found

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


_U = UserRow.__table__.c
_SUMMARY = select(
    _U.id,
    _U.display_name,
    _U.ui_locale,
    _U.trust_level,
    _U.phone_verified_at,
    _U.status,
    _U.created_at,
)


def _summary(row: RowMapping) -> UserSummary:
    return UserSummary(
        id=UserId(row["id"]),
        display_name=row["display_name"],
        ui_locale=row["ui_locale"],
        trust_level=row["trust_level"],
        phone_verified=row["phone_verified_at"] is not None,
        is_deleted=row["status"] == UserStatus.DELETED,
        created_at=row["created_at"],
    )


def _scheduled(user_id: Any) -> ColumnElement[datetime]:
    d = DeletionRequestRow.__table__.c
    return (
        select(d.execute_after)
        .where(d.user_id == user_id, d.cancelled_at.is_(None), d.completed_at.is_(None))
        .scalar_subquery()
    )


def _json_object(**fields: ColumnElement[Any]) -> ColumnElement[Any]:
    """json_build_object с ключами-литералами: параметр без типа PostgreSQL здесь не примет."""
    pairs = [part for key, value in fields.items() for part in (literal_column(f"'{key}'"), value)]
    return func.json_build_object(*pairs)


def _restrictions_json(user_id: Any, now: datetime) -> ColumnElement[Any]:
    """Неснятые санкции, действующие сейчас или позже, — JSON-массивом (как `restrictions`)."""
    r = RestrictionRow.__table__.c
    return (
        select(
            func.json_agg(
                aggregate_order_by(
                    _json_object(
                        kind=r.kind,
                        reason_code=r.reason_code,
                        starts_at=r.starts_at,
                        ends_at=r.ends_at,
                    ),
                    r.starts_at,
                )
            )
        )
        .where(r.user_id == user_id, r.lifted_at.is_(None))
        .where(or_(r.ends_at.is_(None), r.ends_at > now))
        .scalar_subquery()
    )


def _consents_json(user_id: Any) -> ColumnElement[Any]:
    """Действующие согласия по времени — JSON-массивом (как `consents`)."""
    c = ConsentRow.__table__.c
    return (
        select(
            func.json_agg(
                aggregate_order_by(
                    _json_object(document=c.document, version=c.version, granted_at=c.granted_at),
                    c.granted_at,
                )
            )
        )
        .where(c.user_id == user_id, c.withdrawn_at.is_(None))
        .scalar_subquery()
    )


_ME = select(
    _U.id,
    _U.display_name,
    _U.ui_locale,
    _U.trust_level,
    _U.phone_verified_at,
    _U.created_at,
    _U.version,
    _U.home_city_id,
    _U.intent,
    _U.privacy,
    # ждущий запрос на удаление: S31 показывает дату и «Отменить»
    _scheduled(_U.id).label("deletion_scheduled_at"),
)


def _me(row: RowMapping) -> MeView:
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
        show_telegram=Privacy.from_mapping(row["privacy"] or {}).show_telegram,
    )


def _restriction(item: Mapping[str, Any]) -> Restriction:
    ends_at = item["ends_at"]
    return Restriction(
        kind=RestrictionKind(item["kind"]),
        reason_code=item["reason_code"],
        starts_at=datetime.fromisoformat(item["starts_at"]),
        ends_at=datetime.fromisoformat(ends_at) if ends_at is not None else None,
    )


def _consent(item: Mapping[str, Any]) -> Consent:
    return Consent(
        document=ConsentDocument(item["document"]),
        version=item["version"],
        granted_at=datetime.fromisoformat(item["granted_at"]),
    )
