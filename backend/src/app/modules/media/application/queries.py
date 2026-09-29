"""Чтение файлов для владельца (GET /media/{id})."""

from app.modules.media.application.dto import MediaView
from app.modules.media.application.ports import MediaQuery
from app.modules.media.domain.asset import MediaAsset, MediaStatus
from app.modules.media.errors import MediaNotFoundError
from app.platform.kernel.ids import MediaId, UserId
from app.platform.storage.port import Bucket, StoragePort

PREVIEW_STATUSES = frozenset({MediaStatus.UPLOADED, MediaStatus.PROCESSING})
"""Оригинал показываем владельцу, пока нет вариантов (шаг 2.2); отклонённый — нет."""


class MediaQueries:
    def __init__(self, query: MediaQuery, storage: StoragePort) -> None:
        self._query, self._storage = query, storage

    async def get(self, owner_id: UserId, media_id: MediaId) -> MediaView:
        asset = await self._query.asset(owner_id, media_id)
        if asset is None:
            raise MediaNotFoundError(media_id=media_id)
        return await self.view(asset)

    async def view(self, asset: MediaAsset) -> MediaView:
        preview = None
        if asset.status in PREVIEW_STATUSES:
            preview = await self._storage.presign_get(Bucket(asset.bucket), asset.object_key)
        return MediaView(
            id=asset.id,
            kind=asset.kind,
            purpose=asset.purpose,
            status=asset.status,
            mime_type=asset.mime_type,
            size_bytes=asset.size_bytes,
            moderation_status=asset.moderation_status,
            created_at=asset.created_at,
            uploaded_at=asset.uploaded_at,
            preview_url=preview,
        )
