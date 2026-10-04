"""Реализация MediaApi (ADR-0020 §6): файлы для модулей выше по DAG — портфолио, фото профиля."""

from collections.abc import Collection

from app.modules.media.api import MediaApi, MediaDuplicate, MediaRef, MediaVariantRef
from app.modules.media.application.dto import DiscardMediaPayload, MediaView
from app.modules.media.application.ports import DISCARD_MEDIA, MediaQuery
from app.modules.media.application.queries import MediaQueries
from app.modules.media.domain.asset import DUPLICATE_DISTANCE, MediaStatus
from app.modules.media.domain.policy import MediaPurpose
from app.modules.media.errors import MediaNotFoundError, MediaStateError
from app.platform.kernel.ids import MediaId, UserId
from app.platform.queue.port import JobQueue

ATTACHABLE = frozenset({MediaStatus.UPLOADED, MediaStatus.PROCESSING, MediaStatus.READY})
"""Прикрепить можно загруженный файл — даже пока он обрабатывается: экран ждёт вариантов."""
MAX_DUPLICATES = 5
"""Похожих файлов в ответе: модератору хватит ближних, а массовая копия не раздует кейс."""


class MediaFacade(MediaApi):
    def __init__(self, query: MediaQuery, queries: MediaQueries, queue: JobQueue) -> None:
        self._query, self._queries, self._queue = query, queries, queue

    async def owned(self, owner_id: UserId, media_id: MediaId, *, purpose: str) -> MediaRef:
        asset = await self._query.asset(owner_id, media_id)
        if asset is None:
            raise MediaNotFoundError(media_id=media_id)
        if asset.purpose is not MediaPurpose(purpose) or asset.status not in ATTACHABLE:
            raise MediaStateError(media_status=asset.status.value)
        return _ref(await self._queries.view(asset))

    async def refs(self, media_ids: Collection[MediaId]) -> dict[MediaId, MediaRef]:
        assets = await self._query.assets(media_ids)
        return {asset.id: _ref(await self._queries.view(asset)) for asset in assets}

    async def duplicates(self, media_id: MediaId) -> list[MediaDuplicate]:
        asset = await self._query.asset_by_id(media_id)
        if asset is None or asset.status is not MediaStatus.READY or asset.phash is None:
            return []
        return await self._query.duplicates(
            asset, max_distance=DUPLICATE_DISTANCE, limit=MAX_DUPLICATES
        )

    async def discard(self, owner_id: UserId, media_id: MediaId) -> None:
        await self._queue.enqueue(
            DISCARD_MEDIA,
            DiscardMediaPayload(user_id=owner_id, media_id=media_id),
            dedup_key=str(media_id),
        )


def _ref(view: MediaView) -> MediaRef:
    return MediaRef(
        id=view.id,
        kind=view.kind.value,
        status=view.status.value,
        placeholder=view.placeholder,
        variants=tuple(
            MediaVariantRef(name=v.name, url=v.url, width=v.width, height=v.height)
            for v in view.variants
        ),
        video_url=view.video.url if view.video else None,
        duration_ms=view.duration_ms,
    )
