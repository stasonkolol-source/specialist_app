"""Чтение media без блокировки (ADR-0020 §4, §5): GET /media/{id}, ссылки на части, complete.

Транзакция чтения закрывается сразу после запроса (SqlQuery): `complete` потом ждёт HEAD
хранилища, и соединение с БД в это время не висит «idle in transaction».
"""

from collections.abc import Collection, Sequence
from datetime import datetime

from sqlalchemy import Select, select

from app.modules.media.domain.asset import PUBLIC_PURPOSES, MediaAsset, MediaStatus
from app.modules.media.domain.policy import MediaKind
from app.modules.media.infrastructure.models import AssetRow
from app.modules.media.infrastructure.repositories import to_domain, visible_to
from app.platform.db.query import SqlQuery
from app.platform.kernel.ids import MediaId, UserId


class SqlMediaQuery(SqlQuery):
    async def asset(self, owner_id: UserId, media_id: MediaId) -> MediaAsset | None:
        return await self._one(select(AssetRow).where(*visible_to(owner_id, media_id)))

    async def asset_by_id(self, media_id: MediaId) -> MediaAsset | None:
        return await self._one(select(AssetRow).where(AssetRow.id == media_id))

    async def assets(self, media_ids: Collection[MediaId]) -> list[MediaAsset]:
        if not media_ids:
            return []
        stmt = select(AssetRow).where(
            AssetRow.id.in_(list(media_ids)), AssetRow.deleted_at.is_(None)
        )
        rows = (await self._session.scalars(stmt)).all()
        # в домен — до конца транзакции: после rollback строки ORM истекают
        assets = [to_domain(row) for row in rows]
        await self._release()
        return assets

    async def owned_ids(self, owner_id: UserId) -> list[MediaId]:
        stmt = select(AssetRow.id).where(
            AssetRow.owner_id == owner_id, AssetRow.deleted_at.is_(None)
        )
        ids = [MediaId(media_id) for media_id in (await self._session.scalars(stmt)).all()]
        await self._release()
        return ids

    async def stuck(
        self,
        uploaded_before: datetime,
        uploaded_after: datetime,
        *,
        kinds: Collection[MediaKind],
        limit: int,
    ) -> Sequence[MediaAsset]:
        stmt = (
            select(AssetRow)
            .where(
                AssetRow.status.in_([MediaStatus.UPLOADED, MediaStatus.PROCESSING]),
                AssetRow.kind.in_(list(kinds)),
                AssetRow.uploaded_at < uploaded_before,
                AssetRow.uploaded_at >= uploaded_after,
            )
            .order_by(AssetRow.uploaded_at)
            .limit(limit)
        )
        assets = [to_domain(row) for row in (await self._session.execute(stmt)).scalars()]
        await self._release()
        return assets

    async def unhidden(self, deleted_before: datetime, *, limit: int) -> Sequence[MediaAsset]:
        stmt = (
            select(AssetRow)
            .where(
                AssetRow.status == MediaStatus.DELETED,
                AssetRow.purged_at.is_(None),
                AssetRow.hidden_at.is_(None),
                AssetRow.purpose.in_(PUBLIC_PURPOSES),
                AssetRow.deleted_at < deleted_before,
            )
            .order_by(AssetRow.deleted_at)
            .limit(limit)
        )
        assets = [to_domain(row) for row in (await self._session.execute(stmt)).scalars()]
        await self._release()
        return assets

    async def _one(self, stmt: Select[AssetRow]) -> MediaAsset | None:
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        # в домен — до конца транзакции: после rollback строка ORM истекает
        asset = to_domain(row) if row is not None else None
        await self._release()
        return asset
