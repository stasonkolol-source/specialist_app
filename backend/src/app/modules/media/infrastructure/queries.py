"""Чтение media без блокировки (ADR-0020 §4, §5): GET /media/{id}, ссылки на части, complete.

Транзакция чтения закрывается сразу после запроса (SqlQuery): `complete` потом ждёт HEAD
хранилища, и соединение с БД в это время не висит «idle in transaction».
"""

from collections.abc import Collection, Sequence
from datetime import datetime

from sqlalchemy import Select, and_, func, or_, select

from app.modules.media.api import MediaDuplicate
from app.modules.media.domain.asset import (
    PUBLIC_PURPOSES,
    MediaAsset,
    MediaStatus,
    ModerationStatus,
)
from app.modules.media.domain.policy import MediaKind, MediaPurpose
from app.modules.media.infrastructure.models import AssetRow
from app.modules.media.infrastructure.repositories import phash_bits, to_domain, visible_to
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
        rows = (await self._execute(stmt)).scalars().all()
        # в домен — до конца транзакции: после rollback строки ORM истекают
        assets = [to_domain(row) for row in rows]
        await self._release()
        return assets

    async def owned_ids(self, owner_id: UserId) -> list[MediaId]:
        stmt = select(AssetRow.id).where(
            AssetRow.owner_id == owner_id, AssetRow.deleted_at.is_(None)
        )
        ids = [MediaId(media_id) for media_id in (await self._execute(stmt)).scalars().all()]
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
        assets = [to_domain(row) for row in (await self._execute(stmt)).scalars()]
        await self._release()
        return assets

    async def unhidden(self, deleted_before: datetime, *, limit: int) -> Sequence[MediaAsset]:
        """Удалённые раньше `deleted_before` и отклонённые модерацией (6.7) файлы, обработанные
        раньше него: у отклонённого нет `deleted_at`, а свежий отказ прячет задача решения.
        Варианты, которые могут быть в media, — это файлы без `hidden_at`: возврат снимает
        отметку, если файл снова надо прятать (`MediaAsset.expose`)."""
        stmt = (
            select(AssetRow)
            .where(
                AssetRow.purged_at.is_(None),
                AssetRow.hidden_at.is_(None),
                AssetRow.purpose.in_(PUBLIC_PURPOSES),
                or_(
                    and_(
                        AssetRow.status == MediaStatus.DELETED,
                        AssetRow.deleted_at < deleted_before,
                    ),
                    and_(
                        AssetRow.status == MediaStatus.READY,
                        AssetRow.moderation_status == ModerationStatus.REJECTED,
                        AssetRow.processed_at < deleted_before,
                    ),
                ),
            )
            .order_by(func.coalesce(AssetRow.deleted_at, AssetRow.processed_at))
            .limit(limit)
        )
        assets = [to_domain(row) for row in (await self._execute(stmt)).scalars()]
        await self._release()
        return assets

    async def unchecked(
        self, processed_before: datetime, *, purposes: Collection[MediaPurpose], limit: int
    ) -> Sequence[MediaAsset]:
        """Без индекса, как `duplicates`: на объёмах MVP проход по готовым файлам — миллисекунды
        раз в 10 минут; частичный индекс по `processed_at` — если файлов станет на порядки
        больше."""
        stmt = (
            select(AssetRow)
            .where(
                AssetRow.status == MediaStatus.READY,
                AssetRow.moderation_status == ModerationStatus.PENDING,
                AssetRow.purpose.in_(list(purposes)),
                AssetRow.processed_at < processed_before,
            )
            .order_by(AssetRow.processed_at)
            .limit(limit)
        )
        assets = [to_domain(row) for row in (await self._execute(stmt)).scalars()]
        await self._release()
        return assets

    async def duplicates(
        self, asset: MediaAsset, *, max_distance: int, limit: int
    ) -> list[MediaDuplicate]:
        """Расстояние Хэмминга в PostgreSQL — `bit_count(phash # :phash)`. Без индекса: на
        объёмах MVP (десятки тысяч фото портфолио) полный проход по готовым файлам назначения —
        миллисекунды; индекс по частям хэша (multi-index hashing) — когда фото станет на
        порядки больше (media_0006)."""
        if asset.phash is None:
            return []
        distance = func.bit_count(AssetRow.phash.bitwise_xor(phash_bits(asset.phash)))
        stmt = (
            select(AssetRow.id, AssetRow.owner_id, distance)
            .where(
                AssetRow.purpose == asset.purpose,
                AssetRow.status == MediaStatus.READY,
                AssetRow.owner_id != asset.owner_id,
                AssetRow.phash.is_not(None),
                distance <= max_distance,
            )
            .order_by(distance, AssetRow.id)
            .limit(limit)
        )
        found = [
            MediaDuplicate(media_id=MediaId(media_id), owner_id=UserId(owner_id), distance=bits)
            for media_id, owner_id, bits in (await self._execute(stmt)).all()
        ]
        await self._release()
        return found

    async def _one(self, stmt: Select[AssetRow]) -> MediaAsset | None:
        row = (await self._execute(stmt)).scalar_one_or_none()
        # в домен — до конца транзакции: после rollback строка ORM истекает
        asset = to_domain(row) if row is not None else None
        await self._release()
        return asset
