"""Рассылки (2.7b): репозиторий, чтение счётчиков и кандидаты в получатели.

Кандидаты — своими таблицами (каналы и выбор S43), сегмент — фасадами identity и specialists:
чужих таблиц модуль не читает (ADR-0002).
"""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import RowMapping, and_, case, exists, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.api import IdentityApi
from app.modules.notifications.application.dto import (
    BroadcastContent,
    BroadcastStats,
    BroadcastSummary,
)
from app.modules.notifications.domain.broadcast import (
    Broadcast,
    BroadcastId,
    Segment,
    Targeting,
    dedupe_prefix,
)
from app.modules.notifications.domain.catalog import Channel, EventGroup, NotificationType
from app.modules.notifications.domain.channel import ChannelKind
from app.modules.notifications.domain.notification import DeliveryStatus
from app.modules.notifications.domain.settings import default_for
from app.modules.notifications.errors import BroadcastNotFoundError
from app.modules.notifications.infrastructure.models import (
    BroadcastRow,
    ChannelRow,
    DeliveryRow,
    NotificationRow,
    PreferenceRow,
)
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.db.query import SqlQuery, decode_cursor, encode_cursor
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import CityId, UserId
from app.platform.kernel.localized import LocalizedText
from app.platform.kernel.pagination import Page, PageRequest


class SqlBroadcastRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def add(self, broadcast: Broadcast) -> None:
        self._uow.require_active()
        row = BroadcastRow(id=broadcast.id)
        _apply(broadcast, row)
        self._session.add(row)
        await self._session.flush()

    async def get_for_update(self, broadcast_id: BroadcastId) -> Broadcast:
        self._uow.require_active()
        row = (
            await self._session.execute(
                select(BroadcastRow).where(BroadcastRow.id == broadcast_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise BroadcastNotFoundError()
        return _to_domain(row)

    async def save(self, broadcast: Broadcast) -> None:
        self._uow.require_active()
        row = await self._session.get(BroadcastRow, broadcast.id)
        if row is None:
            raise BroadcastNotFoundError()
        _apply(broadcast, row)
        await self._session.flush()


def _to_domain(row: BroadcastRow) -> Broadcast:
    return Broadcast(
        id=BroadcastId(row.id),
        text=LocalizedText.from_mapping(row.text),
        group=row.event_group,
        targeting=Targeting(
            audience=row.audience, city_id=CityId(row.city_id) if row.city_id else None
        ),
        link=row.link,
        action=row.action,
        created_by=UserId(row.created_by),
        created_at=row.created_at,
        status=row.status,
        starts_at=row.starts_at,
        finished_at=row.finished_at,
        cursor=UserId(row.cursor) if row.cursor else None,
    )


def _apply(broadcast: Broadcast, row: BroadcastRow) -> None:
    row.status = broadcast.status
    row.event_group = broadcast.group
    row.audience = broadcast.targeting.audience
    row.city_id = broadcast.targeting.city_id
    row.text = broadcast.text.to_mapping()
    row.link = broadcast.link
    row.action = broadcast.action
    row.created_by = broadcast.created_by
    row.created_at = broadcast.created_at
    row.starts_at = broadcast.starts_at
    row.finished_at = broadcast.finished_at
    row.cursor = broadcast.cursor


class SqlBroadcastQuery(SqlQuery):
    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        super().__init__(session)
        self._clock = clock

    async def recent(self, page: PageRequest) -> Page[BroadcastSummary]:
        b = BroadcastRow.__table__.c
        stmt = (
            select(BroadcastRow.__table__)
            .order_by(b.created_at.desc(), b.id.desc())
            .limit(page.limit + 1)
        )
        if page.cursor is not None:
            at, last = decode_cursor(page.cursor, (datetime, UUID))
            stmt = stmt.where(tuple_(b.created_at, b.id) < (at, last))
        rows = await self._fetch(stmt)
        items = tuple(_summary(row) for row in rows[: page.limit])
        if len(rows) <= page.limit:
            return Page(items=items)
        return Page(items=items, next_cursor=encode_cursor(items[-1].created_at, items[-1].id))

    async def summary(self, broadcast_id: BroadcastId) -> BroadcastSummary | None:
        b = BroadcastRow.__table__.c
        row = await self._fetch_one(select(BroadcastRow.__table__).where(b.id == broadcast_id))
        return _summary(row) if row is not None else None

    async def content(self, broadcast_id: BroadcastId) -> BroadcastContent | None:
        b = BroadcastRow.__table__.c
        row = await self._fetch_one(
            select(b.id, b.status, b.text, b.link, b.action).where(b.id == broadcast_id)
        )
        if row is None:
            return None
        return BroadcastContent(
            id=row["id"],
            status=str(row["status"]),
            text=dict(row["text"]),
            link=row["link"],
            action=str(row["action"]) if row["action"] else None,
        )

    async def stats(self, broadcast_id: BroadcastId) -> BroadcastStats:
        n, d = NotificationRow.__table__.c, DeliveryRow.__table__.c
        mine = and_(
            n.type == NotificationType.BROADCAST,
            n.dedupe_key.startswith(dedupe_prefix(broadcast_id), autoescape=True),
        )
        recipients = await self._fetch_one(select(func.count().label("n")).where(mine))
        later = and_(d.status == DeliveryStatus.QUEUED, d.not_before > self._clock.now())
        rows = await self._fetch(
            select(
                d.status,
                func.count().label("n"),
                func.count(case((later, 1))).label("later"),
            )
            .select_from(
                DeliveryRow.__table__.join(NotificationRow.__table__, n.id == d.notification_id)
            )
            .where(mine)
            .group_by(d.status)
        )
        by_status = {DeliveryStatus(row["status"]): int(row["n"]) for row in rows}
        total = int(recipients["n"]) if recipients is not None else 0
        delivered = sum(by_status.values())
        return BroadcastStats(
            recipients=total,
            queued=by_status.get(DeliveryStatus.QUEUED, 0),
            deferred=sum(int(row["later"]) for row in rows),
            sent=by_status.get(DeliveryStatus.SENT, 0),
            failed=by_status.get(DeliveryStatus.FAILED, 0),
            skipped=by_status.get(DeliveryStatus.SUPPRESSED, 0) + total - delivered,
        )

    async def pending(self, broadcast_id: BroadcastId) -> int:
        return (await self.stats(broadcast_id)).queued


class FacadeAudienceSource:
    """Кандидаты — по своим таблицам, сегмент — фасадами модулей ниже по DAG."""

    def __init__(
        self, session: AsyncSession, identity: IdentityApi, specialists: SpecialistsApi
    ) -> None:
        self._session = session
        self._identity, self._specialists = identity, specialists

    async def candidates(
        self, group: EventGroup, *, after: UserId | None, limit: int
    ) -> list[UserId]:
        c, p = ChannelRow.__table__.c, PreferenceRow.__table__.c
        choice = and_(p.user_id == c.user_id, p.event_group == group, p.channel == Channel.TELEGRAM)
        # opt-in — только явным выбором; группа по умолчанию включена — если её не выключали
        allowed = (
            exists().where(choice, p.enabled)
            if not default_for(group)
            else ~exists().where(choice, ~p.enabled)
        )
        stmt = (
            select(c.user_id)
            .where(c.kind == ChannelKind.TELEGRAM, c.disabled_at.is_(None), allowed)
            .order_by(c.user_id)
            .limit(limit)
        )
        if after is not None:
            stmt = stmt.where(c.user_id > after)
        rows = await self._session.execute(stmt)
        return [UserId(row[0]) for row in rows]

    async def segments(self, user_ids: Collection[UserId]) -> dict[UserId, Segment]:
        if not user_ids:
            return {}
        users = await self._identity.users(user_ids)
        profiles = await self._specialists.profiles_of(list(users))
        found: dict[UserId, Segment] = {}
        for user_id, user in users.items():
            if user.is_deleted:
                continue
            profile = profiles.get(user_id)
            found[user_id] = Segment(
                is_specialist=profile is not None,
                is_founding=profile is not None and profile.is_founding,
                city_id=profile.city_id if profile is not None else user.home_city_id,
            )
        return found


def _summary(row: RowMapping) -> BroadcastSummary:
    return BroadcastSummary(
        id=row["id"],
        status=str(getattr(row["status"], "value", row["status"])),
        group=str(getattr(row["event_group"], "value", row["event_group"])),
        audience=str(getattr(row["audience"], "value", row["audience"])),
        city_id=row["city_id"],
        text=dict(row["text"]),
        link=row["link"],
        action=str(getattr(row["action"], "value", row["action"])) if row["action"] else None,
        created_by=UserId(row["created_by"]),
        created_at=row["created_at"],
        starts_at=row["starts_at"],
        finished_at=row["finished_at"],
    )
