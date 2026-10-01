"""Портфолио в PostgreSQL (ADR-0020 §5): работа — строка portfolio_items и её файл в
portfolio_media (в MVP — один)."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.specialists.domain.portfolio import (
    PortfolioItem,
    PortfolioItemId,
    WorkKind,
)
from app.modules.specialists.errors import PortfolioItemNotFoundError
from app.modules.specialists.infrastructure.models import PortfolioItemRow, PortfolioMediaRow
from app.platform.db.port import UnitOfWork
from app.platform.db.query import SqlQuery
from app.platform.kernel.ids import MediaId

_ROWS = (PortfolioItemRow, PortfolioMediaRow)


def _alive(profile_id: UUID) -> Select[PortfolioItemRow, PortfolioMediaRow]:
    return (
        select(*_ROWS)
        .join(PortfolioMediaRow, PortfolioMediaRow.item_id == PortfolioItemRow.id)
        .where(PortfolioItemRow.profile_id == profile_id, PortfolioItemRow.deleted_at.is_(None))
        .order_by(PortfolioItemRow.position, PortfolioItemRow.created_at)
    )


class SqlPortfolioRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def list_for_update(self, profile_id: UUID) -> list[PortfolioItem]:
        """Все работы профиля под блокировкой строк (порядок, лимит) — по позиции."""
        self._uow.require_active()
        stmt = (
            _alive(profile_id)
            .with_for_update(of=PortfolioItemRow)
            .execution_options(populate_existing=True)
        )
        rows = (await self._session.execute(stmt)).all()
        items = [_to_domain(item, media) for item, media in rows]
        for item in items:
            self._uow.track(item)
        return items

    async def add(self, item: PortfolioItem) -> None:
        self._uow.require_active()
        row = PortfolioItemRow(id=item.id, created_at=item.created_at)
        _apply(item, row)
        self._session.add(row)
        await self._session.flush()
        self._session.add(
            PortfolioMediaRow(item_id=item.id, media_id=item.media_id, kind=item.kind)
        )
        await self._session.flush()
        self._uow.track(item)

    async def save(self, item: PortfolioItem) -> None:
        self._uow.require_active()
        row = await self._session.get(PortfolioItemRow, item.id)
        if row is None:
            raise PortfolioItemNotFoundError(item_id=item.id)
        _apply(item, row)
        await self._session.flush()
        self._uow.track(item)


class SqlPortfolioQuery(SqlQuery):
    async def of_profile(self, profile_id: UUID) -> list[PortfolioItem]:
        """Работы профиля по порядку — для кабинета S37 (без блокировки)."""
        rows = (await self._session.execute(_alive(profile_id))).all()
        items = [_to_domain(item, media) for item, media in rows]
        await self._release()
        return items


def _to_domain(item: PortfolioItemRow, media: PortfolioMediaRow) -> PortfolioItem:
    return PortfolioItem(
        id=PortfolioItemId(item.id),
        profile_id=item.profile_id,
        media_id=MediaId(media.media_id),
        kind=WorkKind(media.kind),
        caption=item.title,
        position=item.position,
        status=item.status,
        created_at=item.created_at,
        deleted_at=item.deleted_at,
    )


def _apply(item: PortfolioItem, row: PortfolioItemRow) -> None:
    row.profile_id = item.profile_id
    row.title = item.caption
    row.position = item.position
    row.status = item.status
    row.deleted_at = item.deleted_at


__all__: Sequence[str] = ("SqlPortfolioQuery", "SqlPortfolioRepository")
