"""Ссылки на загрузку (ADR-0007, docs/spikes/0.24-webview-upload.md).

Одним PUT — подпись включает Content-Type и Content-Length: файл другого размера или типа
хранилище отвергнет ещё до записи. Multipart — по частям PART_SIZE, у каждой части свой
подписанный размер; последняя — остаток.
"""

import math
from collections.abc import Iterable

from app.modules.media.application.dto import (
    DeleteObjectsPayload,
    SignedPart,
    StoredRef,
    UploadPlan,
)
from app.modules.media.domain.asset import MediaAsset
from app.platform.kernel.errors import DomainValidationError
from app.platform.storage.port import PART_SIZE, Bucket, StoragePort


def part_count(size_bytes: int) -> int:
    return math.ceil(size_bytes / PART_SIZE)


def part_size(size_bytes: int, number: int) -> int:
    return min(PART_SIZE, size_bytes - (number - 1) * PART_SIZE)


async def upload_plan(
    storage: StoragePort, asset: MediaAsset, part_numbers: Iterable[int] | None = None
) -> UploadPlan:
    """Свежие ссылки на загрузку: все или только `part_numbers` (повтор после обрыва)."""
    bucket = Bucket(asset.bucket)
    if asset.upload_id is None:
        signed = await storage.presign_put(
            bucket, asset.object_key, content_type=asset.mime_type, size=asset.size_bytes
        )
        parts = (SignedPart(part_number=None, url=signed.url, headers=dict(signed.headers)),)
        return UploadPlan(
            media_id=asset.id,
            multipart=False,
            part_size=None,
            parts=parts,
            expires_at=signed.expires_at,
        )
    total = part_count(asset.size_bytes)
    numbers = sorted(set(part_numbers)) if part_numbers is not None else list(range(1, total + 1))
    if not numbers or any(not 1 <= n <= total for n in numbers):
        raise DomainValidationError(field="part_numbers", parts=total)
    signed_parts = [
        await storage.presign_part(
            bucket,
            asset.object_key,
            upload_id=asset.upload_id,
            part_number=n,
            size=part_size(asset.size_bytes, n),
        )
        for n in numbers
    ]
    return UploadPlan(
        media_id=asset.id,
        multipart=True,
        part_size=PART_SIZE,
        parts=tuple(
            SignedPart(part_number=n, url=s.url, headers=dict(s.headers))
            for n, s in zip(numbers, signed_parts, strict=True)
        ),
        expires_at=min(s.expires_at for s in signed_parts),
    )


def delete_original(asset: MediaAsset) -> DeleteObjectsPayload:
    """Оригинал в incoming; незавершённый multipart отменяется."""
    return DeleteObjectsPayload(
        media_id=asset.id,
        objects=(StoredRef(bucket=asset.bucket, key=asset.object_key),),
        upload_id=asset.upload_id,
    )


def delete_variants(
    asset: MediaAsset, bucket: str, *, with_original: bool = False
) -> DeleteObjectsPayload:
    """Все возможные варианты в `bucket` (и оригинал): прерванный запуск мог оставить часть."""
    original = delete_original(asset).objects if with_original else ()
    return DeleteObjectsPayload(
        media_id=asset.id,
        objects=original + tuple(StoredRef(bucket=bucket, key=key) for key in asset.variant_keys()),
        upload_id=asset.upload_id if with_original else None,
    )


def delete_everything(asset: MediaAsset) -> DeleteObjectsPayload:
    """Очистка удалённого файла: оригинал и варианты в обоих бакетах."""
    return DeleteObjectsPayload(
        media_id=asset.id,
        objects=tuple(StoredRef(bucket=bucket, key=key) for bucket, key in asset.objects()),
    )
