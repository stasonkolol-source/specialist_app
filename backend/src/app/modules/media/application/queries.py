"""Чтение файлов для владельца (GET /media/{id}) и адреса вариантов (ARCHITECTURE §10.4).

Пока файл обрабатывается, владелец видит оригинал по presigned GET на 5 минут. Готовый
файл — варианты: публичные адреса CDN с неизменяемыми ключами, а где CDN нет (dev,
тесты) — presigned GET бакета media на час.
"""

from app.modules.media.application.config import VARIANT_URL_TTL, MediaConfig
from app.modules.media.application.dto import MediaView, VariantView
from app.modules.media.application.ports import MediaQuery
from app.modules.media.domain.asset import (
    MEDIA_BUCKET,
    VARIANT_SIDES,
    MediaAsset,
    MediaStatus,
    VariantName,
    variant_bucket,
)
from app.modules.media.errors import MediaNotFoundError
from app.platform.kernel.ids import MediaId, UserId
from app.platform.storage.port import Bucket, StoragePort

PREVIEW_STATUSES = frozenset({MediaStatus.UPLOADED, MediaStatus.PROCESSING})
"""Оригинал показываем владельцу, пока нет вариантов; отклонённый — нет."""


class MediaQueries:
    def __init__(self, query: MediaQuery, storage: StoragePort, config: MediaConfig) -> None:
        self._query, self._storage, self._config = query, storage, config

    async def get(self, owner_id: UserId, media_id: MediaId) -> MediaView:
        asset = await self._query.asset(owner_id, media_id)
        if asset is None:
            raise MediaNotFoundError(media_id=media_id)
        return await self.view(asset)

    async def view(self, asset: MediaAsset) -> MediaView:
        preview = None
        if asset.status in PREVIEW_STATUSES:
            preview = await self._storage.presign_get(Bucket(asset.bucket), asset.object_key)
        variants: list[VariantView] = []
        video = None
        if asset.status is MediaStatus.READY:
            for name, variant in sorted(asset.variants.items(), key=lambda item: item[1].width):
                view = VariantView(
                    name=name,
                    url=await self.variant_url(asset, variant.key),
                    width=variant.width,
                    height=variant.height,
                )
                if name == VariantName.VIDEO:
                    video = view
                elif name in VARIANT_SIDES:
                    variants.append(view)
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
            width=asset.width,
            height=asset.height,
            duration_ms=asset.duration_ms,
            placeholder=asset.placeholder,
            variants=tuple(variants),
            video=video,
            failure_reason=asset.failure_reason,
        )

    async def variant_url(self, asset: MediaAsset, key: str) -> str:
        """Публичное назначение — CDN (или presigned GET media на час, где CDN нет);
        непубличное — presigned GET private на 5 минут: только тому, кто видит файл."""
        if variant_bucket(asset.purpose) != MEDIA_BUCKET:
            return await self._storage.presign_get(Bucket.PRIVATE, key)
        if self._config.public_base_url:
            return f"{self._config.public_base_url.rstrip('/')}/{key}"
        return await self._storage.presign_get(Bucket.MEDIA, key, ttl=VARIANT_URL_TTL)
