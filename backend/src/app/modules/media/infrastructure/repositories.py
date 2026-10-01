"""Репозиторий media.assets (ADR-0020 §5): агрегат MediaAsset ↔ AssetRow."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.media.domain.asset import MediaAsset, MediaStatus, Variant
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

    async def get_for_update(self, owner_id: UserId, media_id: MediaId) -> MediaAsset:
        self._uow.require_active()
        stmt = (
            select(AssetRow)
            .where(*visible_to(owner_id, media_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:  # нет или чужой: владелец чужого файла о нём не узнаёт
            raise MediaNotFoundError(media_id=media_id)
        asset = to_domain(row)
        self._uow.track(asset)
        return asset

    async def get_by_id_for_update(self, media_id: MediaId) -> MediaAsset:
        self._uow.require_active()
        stmt = (
            select(AssetRow)
            .where(AssetRow.id == media_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise MediaNotFoundError(media_id=media_id)
        asset = to_domain(row)
        self._uow.track(asset)
        return asset

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
        return await self._locked(stmt)

    async def deleted_before(
        self, before: datetime, *, now: datetime, limit: int
    ) -> Sequence[MediaAsset]:
        self._uow.require_active()
        stmt = (
            select(AssetRow)
            .where(
                AssetRow.status == MediaStatus.DELETED,
                AssetRow.purged_at.is_(None),
                AssetRow.deleted_at < before,
                or_(AssetRow.held_until.is_(None), AssetRow.held_until <= now),
            )
            .order_by(AssetRow.deleted_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        return await self._locked(stmt)

    async def _locked(self, stmt: Select[AssetRow]) -> Sequence[MediaAsset]:
        assets = [to_domain(row) for row in (await self._session.execute(stmt)).scalars()]
        for asset in assets:
            self._uow.track(asset)
        return assets


def visible_to(owner_id: UserId, media_id: MediaId) -> tuple[ColumnElement[bool], ...]:
    """Файл владельца, кроме удалённого: чужой и удалённый для API одинаково не существуют."""
    return (
        AssetRow.id == media_id,
        AssetRow.owner_id == owner_id,
        AssetRow.status != MediaStatus.DELETED,
    )


def to_domain(row: AssetRow) -> MediaAsset:
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
        etag=row.etag,
        uploaded_at=row.uploaded_at,
        failure_reason=row.failure_reason,
        moderation_status=row.moderation_status,
        width=row.width,
        height=row.height,
        duration_ms=row.duration_ms,
        placeholder=row.placeholder,
        sha256=row.sha256,
        variants={
            name: Variant(key=value["key"], width=value["w"], height=value["h"])
            for name, value in row.variants.items()
        },
        processed_at=row.processed_at,
        attempts=row.attempts,
        deleted_at=row.deleted_at,
        hidden_at=row.hidden_at,
        held_until=row.held_until,
        purged_at=row.purged_at,
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
    row.etag = asset.etag
    row.moderation_status = asset.moderation_status
    row.failure_reason = asset.failure_reason
    row.created_at = asset.created_at
    row.uploaded_at = asset.uploaded_at
    row.width = asset.width
    row.height = asset.height
    row.duration_ms = asset.duration_ms
    row.placeholder = asset.placeholder
    row.sha256 = asset.sha256
    row.variants = {
        name: {"key": v.key, "w": v.width, "h": v.height} for name, v in asset.variants.items()
    }
    row.processed_at = asset.processed_at
    row.attempts = asset.attempts
    row.deleted_at = asset.deleted_at
    row.hidden_at = asset.hidden_at
    row.held_until = asset.held_until
    row.purged_at = asset.purged_at
