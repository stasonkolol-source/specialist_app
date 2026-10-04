"""Реализация MediaApi (ADR-0020 §6): файлы для модулей выше по DAG — портфолио, фото профиля,
модерация фото (6.7)."""

from collections.abc import Collection, Mapping
from typing import Final

from app.modules.media.api import (
    ImageForCheck,
    MediaApi,
    MediaDuplicate,
    MediaModeration,
    MediaRef,
    MediaVariantRef,
    ModerationVerdict,
)
from app.modules.media.application.dto import DiscardMediaPayload, HideVariantsPayload, MediaView
from app.modules.media.application.ports import (
    DISCARD_MEDIA,
    HIDE_VARIANTS,
    RESTORE_VARIANTS,
    MediaQuery,
    MediaRepository,
)
from app.modules.media.application.queries import MediaQueries
from app.modules.media.domain.asset import (
    DUPLICATE_DISTANCE,
    PRIVATE_BUCKET,
    MediaStatus,
    ModerationStatus,
    VariantName,
    variant_bucket,
)
from app.modules.media.domain.policy import MediaPurpose
from app.modules.media.errors import MediaNotFoundError, MediaStateError
from app.platform.kernel.ids import MediaId, UserId
from app.platform.queue.port import JobQueue
from app.platform.storage.port import Bucket, StoragePort, StorageRejectedError

ATTACHABLE = frozenset({MediaStatus.UPLOADED, MediaStatus.PROCESSING, MediaStatus.READY})
"""Прикрепить можно загруженный файл — даже пока он обрабатывается: экран ждёт вариантов."""
MAX_DUPLICATES = 5
"""Похожих файлов в ответе: модератору хватит ближних, а массовая копия не раздует кейс."""
CHECK_VARIANTS: Final = (VariantName.MD, VariantName.LG, VariantName.THUMB)
"""Что отдать на проверку: `md` (800 px) — omni-moderation больше не нужно; маленькое фото
получает меньше вариантов — тогда ближний из оставшихся."""
CHECK_MAX_BYTES: Final = 4 * 1024 * 1024
"""Предел чтения варианта: WebP 800 px — сотни килобайт; провайдер принимает до 20 MB."""


class MediaFacade(MediaApi):
    def __init__(
        self,
        query: MediaQuery,
        queries: MediaQueries,
        queue: JobQueue,
        assets: MediaRepository,
        storage: StoragePort,
    ) -> None:
        self._query, self._queries, self._queue = query, queries, queue
        self._assets, self._storage = assets, storage

    async def owned(self, owner_id: UserId, media_id: MediaId, *, purpose: str) -> MediaRef:
        asset = await self._query.asset(owner_id, media_id)
        if asset is None:
            raise MediaNotFoundError(media_id=media_id)
        if asset.purpose is not MediaPurpose(purpose) or asset.status not in ATTACHABLE:
            raise MediaStateError(media_status=asset.status.value)
        if asset.blocked:  # отклонён модерацией: прикреплять нечего, как отказ обработки
            raise MediaStateError(media_status=MediaStatus.REJECTED.value)
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

    async def image_for_check(self, media_id: MediaId) -> ImageForCheck | None:
        asset = await self._query.asset_by_id(media_id)
        if (
            asset is None
            or asset.status is not MediaStatus.READY
            or asset.moderation_status is not ModerationStatus.PENDING
        ):
            return None
        variant = next((asset.variants[n] for n in CHECK_VARIANTS if n in asset.variants), None)
        if variant is None:
            return None
        bucket = PRIVATE_BUCKET if asset.hidden_at is not None else variant_bucket(asset.purpose)
        try:
            body = await self._storage.get(Bucket(bucket), variant.key, max_bytes=CHECK_MAX_BYTES)
        except StorageRejectedError:  # вариант пропал (файл удаляют) — проверять нечего
            return None
        return ImageForCheck(body=body, content_type="image/webp")

    async def moderate(
        self,
        media_id: MediaId,
        verdict: ModerationVerdict,
        *,
        labels: Mapping[str, float] | None = None,
        auto: bool = False,
    ) -> bool:
        return await record_verdict(
            self._assets, self._queue, media_id, verdict, labels=labels, auto=auto
        )

    async def discard(self, owner_id: UserId, media_id: MediaId) -> None:
        await self._queue.enqueue(
            DISCARD_MEDIA,
            DiscardMediaPayload(user_id=owner_id, media_id=media_id),
            dedup_key=str(media_id),
        )


class MediaModerator(MediaModeration):
    """Решения по фото без хранилища (порт `MediaModeration`): адаптер цели «фото» модерации."""

    def __init__(self, assets: MediaRepository, queue: JobQueue) -> None:
        self._assets, self._queue = assets, queue

    async def verdict(self, media_id: MediaId) -> ModerationVerdict | None:
        try:
            asset = await self._assets.get_by_id_for_update(media_id)
        except MediaNotFoundError:
            return None
        if asset.status is not MediaStatus.READY:
            return None
        if asset.moderation_status is ModerationStatus.PENDING:
            return None
        return ModerationVerdict(asset.moderation_status.value)

    async def moderate(
        self,
        media_id: MediaId,
        verdict: ModerationVerdict,
        *,
        labels: Mapping[str, float] | None = None,
        auto: bool = False,
    ) -> bool:
        return await record_verdict(
            self._assets, self._queue, media_id, verdict, labels=labels, auto=auto
        )


async def record_verdict(
    assets: MediaRepository,
    queue: JobQueue,
    media_id: MediaId,
    verdict: ModerationVerdict,
    *,
    labels: Mapping[str, float] | None,
    auto: bool,
) -> bool:
    """Итог проверки фото — в транзакции вызывающего (`MediaApi.moderate`)."""
    try:
        asset = await assets.get_by_id_for_update(media_id)
    except MediaNotFoundError:
        return False
    if not asset.moderate(ModerationStatus(verdict.value), labels=labels, auto=auto):
        return False
    await assets.save(asset)
    payload = HideVariantsPayload(media_id=asset.id, keys=asset.variant_keys())
    if asset.blocked and asset.hidden_at is None:
        await queue.enqueue(HIDE_VARIANTS, payload, dedup_key=str(asset.id))
    elif not asset.blocked and asset.hidden_at is not None:
        await queue.enqueue(RESTORE_VARIANTS, payload, dedup_key=str(asset.id))
    return True


def _ref(view: MediaView) -> MediaRef:
    """Отклонённый модерацией (6.7) для других — как отказ обработки: ни вариантов, ни превью."""
    blocked = view.moderation_status is ModerationStatus.REJECTED
    return MediaRef(
        id=view.id,
        kind=view.kind.value,
        status=MediaStatus.REJECTED.value if blocked else view.status.value,
        placeholder=None if blocked else view.placeholder,
        variants=tuple(
            MediaVariantRef(name=v.name, url=v.url, width=v.width, height=v.height)
            for v in view.variants
        ),
        video_url=view.video.url if view.video else None,
        duration_ms=view.duration_ms,
    )
