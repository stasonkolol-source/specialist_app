"""Чтение notifications без блокировок (ADR-0020 §4, §5): центр, доставки, настройки."""

from uuid import UUID

from sqlalchemy import func, select

from app.modules.notifications.application.dto import (
    ChannelView,
    DeliveryTarget,
    NotificationRecord,
)
from app.modules.notifications.domain.channel import ChannelKind
from app.modules.notifications.domain.notification import DeliveryId, NotificationId
from app.modules.notifications.domain.settings import NotificationSettings
from app.modules.notifications.infrastructure.models import (
    ChannelRow,
    DeliveryRow,
    NotificationRow,
    PreferenceRow,
    UserSettingsRow,
)
from app.modules.notifications.infrastructure.repositories import (
    params_of,
    settings_of,
    valid_until_of,
)
from app.platform.db.query import SqlQuery, decode_cursor, encode_cursor
from app.platform.kernel.ids import UserId
from app.platform.kernel.pagination import Page, PageRequest


class SqlNotificationQuery(SqlQuery):
    async def page(self, user_id: UserId, request: PageRequest) -> Page[NotificationRecord]:
        n = NotificationRow.__table__.c
        stmt = (
            select(n.id, n.type, n.payload, n.created_at, n.read_at)
            .where(n.user_id == user_id, n.in_app)
            .order_by(n.id.desc())
            .limit(request.limit + 1)
        )
        if request.cursor is not None:
            (after,) = decode_cursor(request.cursor, (UUID,))
            stmt = stmt.where(n.id < after)
        rows = await self._fetch(stmt)
        items = tuple(
            NotificationRecord(
                id=NotificationId(row["id"]),
                type=row["type"],
                params=params_of(row["payload"]),
                link=row["payload"].get("link"),
                created_at=row["created_at"],
                read_at=row["read_at"],
            )
            for row in rows[: request.limit]
        )
        more = len(rows) > request.limit
        return Page(items=items, next_cursor=encode_cursor(items[-1].id) if more else None)

    async def unread(self, user_id: UserId) -> int:
        n = NotificationRow.__table__.c
        row = await self._fetch_one(
            select(func.count().label("unread")).where(
                n.user_id == user_id, n.in_app, n.read_at.is_(None)
            )
        )
        return int(row["unread"]) if row is not None else 0

    async def delivery(self, delivery_id: DeliveryId) -> DeliveryTarget | None:
        d, n, c = DeliveryRow.__table__.c, NotificationRow.__table__.c, ChannelRow.__table__.c
        row = await self._fetch_one(
            select(
                d.id,
                d.status,
                d.not_before,
                n.user_id,
                n.type,
                n.payload,
                c.id.label("channel_id"),
                c.address,
                c.disabled_at,
            )
            .join_from(DeliveryRow, NotificationRow, d.notification_id == n.id)
            .join(ChannelRow, d.channel_id == c.id)
            .where(d.id == delivery_id)
        )
        if row is None:
            return None
        return DeliveryTarget(
            id=DeliveryId(row["id"]),
            status=row["status"],
            not_before=row["not_before"],
            user_id=UserId(row["user_id"]),
            channel_id=row["channel_id"],
            chat_id=int(row["address"]),
            writable=row["disabled_at"] is None,
            type=row["type"],
            params=params_of(row["payload"]),
            link=row["payload"].get("link"),
            urgent=bool(row["payload"].get("urgent", False)),
            valid_until=valid_until_of(row["payload"]),
        )

    async def deliveries_of(self, notification_id: NotificationId) -> list[DeliveryId]:
        d = DeliveryRow.__table__.c
        rows = await self._fetch(
            select(d.id).where(d.notification_id == notification_id).order_by(d.id)
        )
        return [DeliveryId(row["id"]) for row in rows]

    async def settings(self, user_id: UserId) -> NotificationSettings:
        p, s = PreferenceRow.__table__.c, UserSettingsRow.__table__.c
        choices = (
            await self._execute(
                select(p.event_group, p.channel, p.enabled).where(p.user_id == user_id)
            )
        ).all()
        row = await self._fetch_one(
            select(s.quiet_enabled, s.quiet_start, s.quiet_end, s.digest_hour).where(
                s.user_id == user_id
            )
        )
        return settings_of(
            [(r.event_group, r.channel, r.enabled) for r in choices],
            (row["quiet_enabled"], row["quiet_start"], row["quiet_end"], row["digest_hour"])
            if row is not None
            else None,
        )

    async def telegram_channel(self, user_id: UserId) -> ChannelView | None:
        c = ChannelRow.__table__.c
        row = await self._fetch_one(
            select(c.kind, c.granted_via, c.granted_at, c.disabled_at).where(
                c.user_id == user_id, c.kind == ChannelKind.TELEGRAM
            )
        )
        if row is None:
            return None
        return ChannelView(
            kind=row["kind"],
            granted_via=row["granted_via"],
            granted_at=row["granted_at"],
            disabled_at=row["disabled_at"],
        )
