"""Репозитории notifications (ADR-0020 §5): простая запись без агрегата."""

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.api import UserNotFoundError
from app.modules.notifications.application.dto import ChannelView
from app.modules.notifications.domain.channel import ChannelKind, GrantedVia
from app.modules.notifications.infrastructure.models import ChannelRow
from app.platform.db.constraints import raise_domain_error
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId, new_id


class SqlChannelRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def grant_telegram(
        self, user_id: UserId, chat_id: int, *, via: GrantedVia, now: datetime
    ) -> ChannelView:
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
        # (403) включается; чат, перешедший к другому аккаунту, переходит вместе с ним.
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
                ChannelRow.disabled_at.is_not(None), ChannelRow.user_id != stmt.excluded.user_id
            ),
        )
        try:
            await self._session.execute(stmt)
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
        return ChannelView(
            kind=row["kind"],
            granted_via=row["granted_via"],
            granted_at=row["granted_at"],
            disabled_at=row["disabled_at"],
        )
