"""Репозитории notifications (ADR-0020 §5): простые записи без агрегата."""

from collections.abc import Collection, Iterable, Mapping
from datetime import datetime, time
from types import MappingProxyType
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.api import UserNotFoundError
from app.modules.notifications.application.dto import (
    ChannelView,
    NewNotification,
    TelegramTarget,
)
from app.modules.notifications.domain.catalog import Channel, EventGroup
from app.modules.notifications.domain.channel import ChannelKind, GrantedVia
from app.modules.notifications.domain.notification import (
    DeliveryId,
    DeliveryStatus,
    NotificationId,
)
from app.modules.notifications.domain.settings import (
    NotificationSettings,
    Preferences,
    QuietHours,
)
from app.modules.notifications.infrastructure.models import (
    ChannelRow,
    DeliveryRow,
    NotificationRow,
    PreferenceRow,
    UserSettingsRow,
)
from app.platform.db.constraints import raise_domain_error
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId, new_id


class SqlChannelRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def grant_telegram(
        self, user_id: UserId, chat_id: int, *, via: GrantedVia, now: datetime
    ) -> tuple[ChannelView, bool]:
        self._uow.require_active()
        address = str(chat_id)
        stmt = insert(ChannelRow).values(
            id=new_id(),
            user_id=user_id,
            kind=ChannelKind.TELEGRAM,
            address=address,
            granted_via=via,
            granted_at=now,
        )
        # Доступный канал того же пользователя не трогаем: повтор идемпотентен. Выключенный
        # включается, только если разрешение новее выключения: /start, обработанный после
        # остановки бота, но нажатый до неё, канал не включит. Чат, перешедший к другому
        # аккаунту, переходит вместе с ним.
        stmt = stmt.on_conflict_do_update(
            index_elements=["kind", "address"],
            set_={
                "user_id": stmt.excluded.user_id,
                "granted_via": stmt.excluded.granted_via,
                "granted_at": stmt.excluded.granted_at,
                "disabled_at": None,
                "updated_at": func.now(),
            },
            where=or_(
                ChannelRow.disabled_at < stmt.excluded.granted_at,
                ChannelRow.user_id != stmt.excluded.user_id,
            ),
        )
        try:
            # RETURNING отдаёт строку, только если вставка или UPDATE сработали: повтор при
            # доступном канале (WHERE ложен) строк не возвращает
            changed = (await self._session.execute(stmt.returning(ChannelRow.id))).first()
        except IntegrityError as err:
            raise_domain_error(
                err, {"fk_channels_user_id_users": lambda: UserNotFoundError(user_id=user_id)}
            )
        c = ChannelRow.__table__.c
        row = (
            (
                await self._session.execute(
                    select(c.kind, c.granted_via, c.granted_at, c.disabled_at).where(
                        c.kind == ChannelKind.TELEGRAM, c.address == address
                    )
                )
            )
            .mappings()
            .one()
        )
        view = ChannelView(
            kind=row["kind"],
            granted_via=row["granted_via"],
            granted_at=row["granted_at"],
            disabled_at=row["disabled_at"],
        )
        return view, changed is not None

    async def telegram_target(self, user_id: UserId) -> TelegramTarget | None:
        self._uow.require_active()
        c = ChannelRow.__table__.c
        row = (
            await self._session.execute(
                select(c.id, c.disabled_at).where(
                    c.user_id == user_id, c.kind == ChannelKind.TELEGRAM
                )
            )
        ).first()
        if row is None:
            return None
        return TelegramTarget(channel_id=row.id, writable=row.disabled_at is None)

    async def disable(self, channel_id: UUID, *, at: datetime) -> bool:
        self._uow.require_active()
        stmt = (
            update(ChannelRow)
            .where(
                ChannelRow.id == channel_id,
                ChannelRow.disabled_at.is_(None),
                ChannelRow.granted_at < at,  # разрешение новее — оно и действует
            )
            .values(disabled_at=at, updated_at=func.now())
            .returning(ChannelRow.id)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def disable_telegram(self, user_id: UserId, *, at: datetime) -> bool:
        self._uow.require_active()
        stmt = (
            update(ChannelRow)
            .where(
                ChannelRow.user_id == user_id,
                ChannelRow.kind == ChannelKind.TELEGRAM,
                ChannelRow.disabled_at.is_(None),
                ChannelRow.granted_at < at,
            )
            .values(disabled_at=at, updated_at=func.now())
            .returning(ChannelRow.id)
        )
        return (await self._session.execute(stmt)).first() is not None


def payload_of(
    params: Mapping[str, str],
    link: str | None,
    *,
    urgent: bool,
    valid_until: datetime | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"params": dict(params), "link": link, "urgent": urgent}
    if valid_until is not None:
        payload["valid_until"] = valid_until.isoformat()
    return payload


def valid_until_of(payload: Mapping[str, Any]) -> datetime | None:
    value = payload.get("valid_until")
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def params_of(payload: Mapping[str, Any]) -> Mapping[str, str]:
    return MappingProxyType({str(k): str(v) for k, v in payload.get("params", {}).items()})


def settings_of(
    choices: Iterable[tuple[EventGroup, Channel, bool]],
    row: tuple[bool, time, time, int] | None,
) -> NotificationSettings:
    """Настройки из строк preferences и user_settings; строки нет — умолчания."""
    preferences = Preferences(MappingProxyType({(g, c): enabled for g, c, enabled in choices}))
    if row is None:
        return NotificationSettings(preferences=preferences)
    quiet_enabled, quiet_start, quiet_end, digest_hour = row
    return NotificationSettings(
        preferences=preferences,
        quiet_hours=QuietHours(enabled=quiet_enabled, start=quiet_start, end=quiet_end),
        digest_hour=digest_hour,
    )


class SqlNotificationRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def add(self, notification: NewNotification) -> NotificationId | None:
        self._uow.require_active()
        stmt = (
            insert(NotificationRow)
            .values(
                id=new_id(),
                user_id=notification.user_id,
                type=notification.type,
                payload=payload_of(
                    notification.params,
                    notification.link,
                    urgent=notification.urgent,
                    valid_until=notification.valid_until,
                ),
                dedupe_key=notification.dedupe_key,
                priority=int(notification.priority),
                in_app=notification.in_app,
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
            .returning(NotificationRow.id)
        )
        try:
            row = (await self._session.execute(stmt)).first()
        except IntegrityError as err:
            raise_domain_error(
                err,
                {
                    "fk_notifications_user_id_users": lambda: UserNotFoundError(
                        user_id=notification.user_id
                    )
                },
            )
        return NotificationId(row.id) if row is not None else None

    async def add_delivery(
        self, notification_id: NotificationId, channel_id: UUID, *, not_before: datetime
    ) -> DeliveryId:
        self._uow.require_active()
        delivery_id = DeliveryId(new_id())
        await self._session.execute(
            insert(DeliveryRow).values(
                id=delivery_id,
                notification_id=notification_id,
                channel_id=channel_id,
                status=DeliveryStatus.QUEUED,
                not_before=not_before,
            )
        )
        return delivery_id

    async def record_failure(self, delivery_id: DeliveryId, *, error: str) -> int | None:
        self._uow.require_active()
        stmt = (
            update(DeliveryRow)
            .where(DeliveryRow.id == delivery_id, DeliveryRow.status == DeliveryStatus.QUEUED)
            .values(attempts=DeliveryRow.attempts + 1, error=error[:255], updated_at=func.now())
            .returning(DeliveryRow.attempts)
        )
        row = (await self._session.execute(stmt)).first()
        return int(row.attempts) if row is not None else None

    async def expire_stale(self, *, due_before: datetime, limit: int) -> int:
        self._uow.require_active()
        stale = (
            select(DeliveryRow.id)
            .where(DeliveryRow.status == DeliveryStatus.QUEUED, DeliveryRow.not_before < due_before)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        stmt = (
            update(DeliveryRow)
            .where(DeliveryRow.id.in_(stale.scalar_subquery()))
            .values(status=DeliveryStatus.FAILED, error="stale", updated_at=func.now())
            .returning(DeliveryRow.id)
        )
        return len((await self._session.execute(stmt)).all())

    async def postpone_delivery(self, delivery_id: DeliveryId, *, not_before: datetime) -> bool:
        self._uow.require_active()
        stmt = (
            update(DeliveryRow)
            .where(DeliveryRow.id == delivery_id, DeliveryRow.status == DeliveryStatus.QUEUED)
            .values(not_before=not_before, updated_at=func.now())
            .returning(DeliveryRow.id)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def settle_delivery(
        self,
        delivery_id: DeliveryId,
        status: DeliveryStatus,
        *,
        now: datetime,
        provider_message_id: str | None = None,
        error: str | None = None,
        attempt: bool = True,
    ) -> bool:
        self._uow.require_active()
        stmt = (
            update(DeliveryRow)
            .where(DeliveryRow.id == delivery_id, DeliveryRow.status == DeliveryStatus.QUEUED)
            .values(
                status=status,
                attempts=DeliveryRow.attempts + (1 if attempt else 0),
                provider_message_id=provider_message_id,
                error=error,
                sent_at=now if status is DeliveryStatus.SENT else None,
                updated_at=func.now(),
            )
            .returning(DeliveryRow.id)
        )
        return (await self._session.execute(stmt)).first() is not None

    async def mark_read(
        self, user_id: UserId, ids: Collection[NotificationId] | None, *, now: datetime
    ) -> int:
        self._uow.require_active()
        stmt = update(NotificationRow).where(
            NotificationRow.user_id == user_id,
            NotificationRow.in_app,
            NotificationRow.read_at.is_(None),
        )
        if ids is not None:
            stmt = stmt.where(NotificationRow.id.in_(list(ids)))
        result = await self._session.execute(stmt.values(read_at=now).returning(NotificationRow.id))
        return len(result.all())


class SqlSettingsRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def load(self, user_id: UserId) -> NotificationSettings:
        self._uow.require_active()
        p = PreferenceRow.__table__.c
        choices = (
            await self._session.execute(
                select(p.event_group, p.channel, p.enabled).where(p.user_id == user_id)
            )
        ).all()
        s = UserSettingsRow.__table__.c
        row = (
            await self._session.execute(
                select(s.quiet_enabled, s.quiet_start, s.quiet_end, s.digest_hour).where(
                    s.user_id == user_id
                )
            )
        ).first()
        return settings_of(
            [(r.event_group, r.channel, r.enabled) for r in choices],
            (row.quiet_enabled, row.quiet_start, row.quiet_end, row.digest_hour) if row else None,
        )

    async def lock(self, user_id: UserId) -> None:
        self._uow.require_active()
        # строки ещё нет (настройки по умолчанию) — заводим её с умолчаниями из server_default:
        # блокировать нечего, а параллельная вставка ждёт первую
        try:
            await self._session.execute(
                insert(UserSettingsRow).values(user_id=user_id).on_conflict_do_nothing()
            )
        except IntegrityError as err:
            raise_domain_error(
                err, {"fk_user_settings_user_id_users": lambda: UserNotFoundError(user_id=user_id)}
            )
        s = UserSettingsRow.__table__.c
        await self._session.execute(select(s.user_id).where(s.user_id == user_id).with_for_update())

    async def save(self, user_id: UserId, settings: NotificationSettings) -> None:
        self._uow.require_active()
        quiet = settings.quiet_hours
        upsert = insert(UserSettingsRow).values(
            user_id=user_id,
            quiet_enabled=quiet.enabled,
            quiet_start=quiet.start,
            quiet_end=quiet.end,
            digest_hour=settings.digest_hour,
        )
        upsert = upsert.on_conflict_do_update(
            index_elements=["user_id"],
            set_={
                "quiet_enabled": upsert.excluded.quiet_enabled,
                "quiet_start": upsert.excluded.quiet_start,
                "quiet_end": upsert.excluded.quiet_end,
                "digest_hour": upsert.excluded.digest_hour,
                "updated_at": func.now(),
            },
        )
        try:
            await self._session.execute(upsert)
        except IntegrityError as err:
            raise_domain_error(
                err, {"fk_user_settings_user_id_users": lambda: UserNotFoundError(user_id=user_id)}
            )
        await self._session.execute(delete(PreferenceRow).where(PreferenceRow.user_id == user_id))
        overrides = settings.preferences.overrides()
        if overrides:
            await self._session.execute(
                insert(PreferenceRow).values(
                    [
                        {"user_id": user_id, "event_group": g, "channel": c, "enabled": enabled}
                        for (g, c), enabled in overrides.items()
                    ]
                )
            )
