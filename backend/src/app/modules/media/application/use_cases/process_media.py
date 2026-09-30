"""Обработать загруженный файл (задача `media.process`, ARCHITECTURE §10.3, ADR-0007).

Фото — WebP-варианты без метаданных; ролик — MP4 H.264 720p без метаданных, а из его кадра
тот же конвейер фото делает постер (варианты thumb/md/lg и ThumbHash). Документы — v1.

`uploaded → processing → ready / rejected`. Оригинал читается из incoming ровно в той
версии, что сверили при complete (If-Match по ETag): подменённый потом файл — `rejected`
(mismatch). Отклоняют файл только ответы хранилища о самом файле (подменён, пропал,
больше заявленного); остальные 4xx — сбой конфигурации или сети: задача повторится, а не
выбросит чужое фото. Сбой самой обработки (рестарт, OOM-kill, таймаут, наша ошибка) тоже
повторяется — до MAX_ATTEMPTS запусков, потом `rejected`; запуски, умершие вместе с
воркером, тоже считаются: следующий после последнего отклоняет файл, не начиная работу.
Запуск, сорванный хранилищем (5xx, сеть), попытку не тратит: файл тут ни при чём.
Варианты пишутся в бакет назначения до commit: ключи неизменяемые, повтор перезапишет их,
а не размножит. После commit сырой оригинал с EXIF и GPS убирает `media.delete_objects`:
храним только варианты.

Задача идемпотентна: готовый, отклонённый или удалённый файл повтор не трогает; повтор
после сбоя посреди обработки продолжает с `processing`. Если два запуска пересеклись,
второй застаёт итог первого и не трогает его варианты.
"""

from dataclasses import dataclass

import structlog

from app.modules.media.application.dto import ImageVariant
from app.modules.media.application.ports import (
    DELETE_OBJECTS,
    ImageProcessor,
    MediaQuery,
    MediaRepository,
    ProcessingCrashedError,
    UnprocessableMediaError,
    VideoProcessor,
)
from app.modules.media.application.uploads import delete_original, delete_variants
from app.modules.media.domain.asset import (
    TO_PROCESS,
    FailureReason,
    MediaAsset,
    MediaStatus,
    Variant,
    VariantName,
    variant_bucket,
    variant_key,
)
from app.modules.media.domain.policy import MediaKind
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import ExternalServiceError
from app.platform.kernel.ids import MediaId
from app.platform.queue.port import JobQueue
from app.platform.storage.port import (
    IMMUTABLE,
    PRIVATE,
    Bucket,
    StoragePort,
    StorageRejectedError,
)

log = structlog.get_logger(__name__)

REJECTED_READS = {
    "PreconditionFailed": FailureReason.MISMATCH,  # подменили после complete
    "412": FailureReason.MISMATCH,  # то же без тела ответа (Garage)
    "TooLarge": FailureReason.MISMATCH,
    "NoSuchKey": FailureReason.UNREADABLE,  # пропал: lifecycle incoming, ручное удаление
    "404": FailureReason.UNREADABLE,
}
"""Ответы хранилища о самом файле. Прочие 4xx (AccessDenied, подпись, часы) — не о файле."""


PROCESSED_KINDS = frozenset({MediaKind.IMAGE, MediaKind.VIDEO})


@dataclass(frozen=True, slots=True, kw_only=True)
class ProcessMediaCommand:
    media_id: MediaId


@dataclass(frozen=True, slots=True, kw_only=True)
class Outcome:
    """Что опубликовать: варианты-картинки (у ролика — постер) и сам ролик."""

    width: int
    height: int
    duration_ms: int | None
    placeholder: str
    sha256: bytes
    images: tuple[ImageVariant, ...]
    video: bytes | None = None


class ProcessMedia:
    def __init__(
        self,
        uow: UnitOfWork,
        assets: MediaRepository,
        query: MediaQuery,
        storage: StoragePort,
        images: ImageProcessor,
        videos: VideoProcessor,
        queue: JobQueue,
        clock: Clock,
    ) -> None:
        self._uow, self._assets, self._query = uow, assets, query
        self._storage, self._images, self._videos = storage, images, videos
        self._queue, self._clock = queue, clock

    async def __call__(self, cmd: ProcessMediaCommand) -> MediaStatus | None:
        """Итоговый статус; None — обрабатывать нечего (готов, удалён, документ)."""
        asset = await self._query.asset_by_id(cmd.media_id)
        if asset is not None and asset.status is MediaStatus.DELETED and asset.purged_at is None:
            # повтор упавшего запуска: удалённому файлу его варианты в публичном бакете не нужны
            async with self._uow:
                await self._drop_variants(asset)
        if asset is None or asset.status not in TO_PROCESS or asset.kind not in PROCESSED_KINDS:
            return None
        async with self._uow:  # GET /media/{id} показывает, что работа идёт
            asset = await self._assets.get_by_id_for_update(cmd.media_id)
            if asset.status is MediaStatus.PROCESSING and asset.out_of_attempts:
                # прошлые запуски умерли вместе с воркером (OOM-kill, рестарт) и до отказа
                # ниже не дошли: ещё одной попытки файл не получит
                log.warning(
                    "media_processing_gave_up", media_id=str(asset.id), attempts=asset.attempts
                )
                asset.give_up(now=self._clock.now())
                await self._rejected(asset)
                return asset.status
            if not asset.start_processing():
                return None
            await self._assets.save(asset)
        try:
            processed = await self._processed(asset)
            variants = await self._publish(asset, processed)
        except UnprocessableMediaError as exc:
            return await self._reject(cmd.media_id, exc.reason)
        except ProcessingCrashedError:
            if not asset.out_of_attempts:
                raise  # повтор задачи (и Sentry): файл тут ни при чём
            log.warning("media_processing_gave_up", media_id=str(asset.id), attempts=asset.attempts)
            return await self._reject(cmd.media_id, FailureReason.UNREADABLE)
        except ExternalServiceError:
            # хранилище недоступно: файл тут ни при чём, и запуск не тратит его попытку —
            # иначе минутный сбой хранилища отклонил бы исправное фото
            await self._uncount_attempt(cmd.media_id)
            raise
        async with self._uow:
            asset = await self._assets.get_by_id_for_update(cmd.media_id)
            if asset.status in {MediaStatus.DELETED, MediaStatus.REJECTED}:
                # удалили, пока обрабатывали, или соседний запуск отклонил файл: наши
                # свежие варианты никому не нужны (его удаление могло пройти раньше наших put)
                await self._drop_variants(asset)
                return asset.status
            if asset.status is not MediaStatus.PROCESSING:  # соседний запуск уже закончил
                return asset.status
            asset.ready(
                width=processed.width,
                height=processed.height,
                duration_ms=processed.duration_ms,
                placeholder=processed.placeholder,
                sha256=processed.sha256,
                variants=variants,
                now=self._clock.now(),
            )
            await self._assets.save(asset)
            await self._drop_original(asset)
        return asset.status

    async def _processed(self, asset: MediaAsset) -> Outcome:
        """Оригинал в сверенной версии (If-Match); ответ хранилища о самом файле — отказ,
        остальное — повтор."""
        source = Bucket(asset.bucket), asset.object_key
        try:
            if asset.kind is MediaKind.VIDEO:
                video = await self._videos.process(
                    *source, max_bytes=asset.size_bytes, etag=asset.etag
                )
            else:
                data = await self._storage.get(*source, max_bytes=asset.size_bytes, etag=asset.etag)
        except StorageRejectedError as exc:
            reason = REJECTED_READS.get(exc.code)
            if reason is None:
                raise ExternalServiceError(service="storage", code=exc.code) from exc
            raise UnprocessableMediaError(reason) from exc
        if asset.kind is MediaKind.VIDEO:
            poster = await self._images.process(video.poster)
            return Outcome(
                width=video.width,
                height=video.height,
                duration_ms=video.duration_ms,
                placeholder=poster.placeholder,
                sha256=video.sha256,
                images=poster.variants,
                video=video.video,
            )
        image = await self._images.process(data)
        return Outcome(
            width=image.width,
            height=image.height,
            duration_ms=None,
            placeholder=image.placeholder,
            sha256=image.sha256,
            images=image.variants,
        )

    async def _publish(self, asset: MediaAsset, processed: Outcome) -> dict[str, Variant]:
        bucket = Bucket(variant_bucket(asset.purpose))
        cache = IMMUTABLE if bucket is Bucket.MEDIA else PRIVATE
        variants: dict[str, Variant] = {}
        for image in processed.images:
            key = variant_key(asset.id, image.name)
            await self._storage.put(
                bucket, key, image.body, content_type="image/webp", cache_control=cache
            )
            variants[image.name] = Variant(key=key, width=image.width, height=image.height)
        if processed.video is not None:
            key = variant_key(asset.id, VariantName.VIDEO)
            await self._storage.put(
                bucket, key, processed.video, content_type="video/mp4", cache_control=cache
            )
            variants[VariantName.VIDEO] = Variant(
                key=key, width=processed.width, height=processed.height
            )
        return variants

    async def _uncount_attempt(self, media_id: MediaId) -> None:
        async with self._uow:
            asset = await self._assets.get_by_id_for_update(media_id)
            if asset.release_attempt():
                await self._assets.save(asset)

    async def _reject(self, media_id: MediaId, reason: FailureReason) -> MediaStatus:
        log.info("media_rejected", media_id=str(media_id), reason=reason.value)
        async with self._uow:
            asset = await self._assets.get_by_id_for_update(media_id)
            if asset.status is not MediaStatus.PROCESSING:  # удалён или соседний запуск успел
                return asset.status
            asset.reject(reason, now=self._clock.now())
            await self._rejected(asset)
        return asset.status

    async def _rejected(self, asset: MediaAsset) -> None:
        """Сохранить отказ; оригинал и остатки вариантов прерванных раньше запусков — прочь."""
        await self._assets.save(asset)
        await self._queue.enqueue(
            DELETE_OBJECTS,
            delete_variants(asset, variant_bucket(asset.purpose), with_original=True),
            dedup_key=f"rejected:{asset.id}",
        )

    async def _drop_original(self, asset: MediaAsset) -> None:
        """Сырой оригинал с EXIF больше не нужен: варианты готовы."""
        await self._queue.enqueue(
            DELETE_OBJECTS, delete_original(asset), dedup_key=f"original:{asset.id}"
        )

    async def _drop_variants(self, asset: MediaAsset) -> None:
        await self._queue.enqueue(
            DELETE_OBJECTS,
            delete_variants(asset, variant_bucket(asset.purpose)),
            dedup_key=f"variants:{asset.id}",
        )
