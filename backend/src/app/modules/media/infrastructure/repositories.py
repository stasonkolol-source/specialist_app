"""Репозиторий media.assets (ADR-0020 §5): агрегат MediaAsset ↔ AssetRow."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.media.domain.asset import MediaAsset, MediaStatus
from app.modules.media.errors import MediaNotFoundError
from app.modules.media.infrastructure.models import AssetRow
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import MediaId, UserId


class SqlMediaRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def add(self, asset: MediaAsset) -> None:
        self._uow.require_active()
        row = AssetRow(id=asset.id)
        _apply(asset, row)
        self._session.add(row)
        await self._session.flush()
        self._uow.track(asset)

    async def get(self, owner_id: UserId, media_id: MediaId) -> MediaAsset:
        return await self._load(owner_id, media_id, lock=False)

    async def get_for_update(self, owner_id: UserId, media_id: MediaId) -> MediaAsset:
        self._uow.require_active()
        return await self._load(owner_id, media_id, lock=True)

    async def save(self, asset: MediaAsset) -> None:
        self._uow.require_active()
        row = await self._session.get(AssetRow, asset.id)
        if row is None:
            raise MediaNotFoundError(media_id=asset.id)
        _apply(asset, row)
        await self._session.flush()
        self._uow.track(asset)

    async def pending_before(self, before: datetime, *, limit: int) -> Sequence[MediaAsset]:
        self._uow.require_active()
        stmt = (
            select(AssetRow)
            .where(AssetRow.status == MediaStatus.PENDING_UPLOAD, AssetRow.created_at < before)
            .order_by(AssetRow.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        assets = [_to_domain(row) for row in (await self._session.execute(stmt)).scalars()]
        for asset in assets:
            self._uow.track(asset)
        return assets

    async def _load(self, owner_id: UserId, media_id: MediaId, *, lock: bool) -> MediaAsset:
        stmt = (
            select(AssetRow)
            .where(
                AssetRow.id == media_id,
                AssetRow.owner_id == owner_id,
                AssetRow.status != MediaStatus.DELETED,
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            stmt = stmt.with_for_update()
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:  # нет или чужой: владелец чужого файла о нём не узнаёт
            raise MediaNotFoundError(media_id=media_id)
        asset = _to_domain(row)
        if lock:
            self._uow.track(asset)
        return asset


def _to_domain(row: AssetRow) -> MediaAsset:
    return MediaAsset(
        id=MediaId(row.id),
        owner_id=UserId(row.owner_id),
        kind=row.kind,
        purpose=row.purpose,
        status=row.status,
        bucket=row.bucket,
        object_key=row.object_key,
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        created_at=row.created_at,
        upload_id=row.upload_id,
        uploaded_at=row.uploaded_at,
        failure_reason=row.failure_reason,
        moderation_status=row.moderation_status,
        deleted_at=row.deleted_at,
    )


def _apply(asset: MediaAsset, row: AssetRow) -> None:
    row.owner_id = asset.owner_id
    row.kind = asset.kind
    row.purpose = asset.purpose
    row.status = asset.status
    row.bucket = asset.bucket
    row.object_key = asset.object_key
    row.upload_id = asset.upload_id
    row.mime_type = asset.mime_type
    row.size_bytes = asset.size_bytes
    row.moderation_status = asset.moderation_status
    row.failure_reason = asset.failure_reason
    row.created_at = asset.created_at
    row.uploaded_at = asset.uploaded_at
    row.deleted_at = asset.deleted_at
