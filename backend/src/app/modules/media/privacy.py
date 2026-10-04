"""Выгрузка данных media (DEVELOPMENT_PLAN 2.12b): файлы пользователя и ссылки на них.

Строки `media.assets` владельца и ссылки на его неудалённые файлы: готовый — варианты, ещё не
обработанный — оригинал. Ссылки — presigned GET на сутки: поддержка отправляет выгрузку сразу,
пользователь успевает скачать, дольше ссылка не живёт. Сроки хранения файлов исполняют свои
задачи: `media.purge_deleted` (удалённые — через 30 дней) и `media.cleanup_orphans`.
"""

from collections.abc import Mapping
from datetime import timedelta
from typing import Any, Final
from uuid import UUID

from dishka import AsyncContainer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.media.domain.asset import MediaStatus, variant_bucket
from app.modules.media.domain.policy import MediaPurpose
from app.modules.media.infrastructure.models import AssetRow
from app.platform.privacy.registry import ExportTable, export_section
from app.platform.storage.port import Bucket, StoragePort

EXPORT_LINK_TTL: Final = timedelta(hours=24)
ORIGINAL_STATUSES: Final = frozenset({MediaStatus.UPLOADED, MediaStatus.PROCESSING})


async def media_links(container: AsyncContainer, user_id: UUID) -> Mapping[str, Any]:
    async with container() as request:
        session = await request.get(AsyncSession)
        rows = (
            await session.execute(
                select(
                    AssetRow.id,
                    AssetRow.purpose,
                    AssetRow.status,
                    AssetRow.bucket,
                    AssetRow.object_key,
                    AssetRow.variants,
                )
                .where(
                    AssetRow.owner_id == user_id,
                    AssetRow.deleted_at.is_(None),
                    AssetRow.status.in_({MediaStatus.READY, *ORIGINAL_STATUSES}),
                )
                .order_by(AssetRow.created_at)
            )
        ).all()
        links: list[dict[str, Any]] = []
        if rows:  # без файлов хранилище не нужно: выгрузка работает и без ключей S3
            storage = await request.get(StoragePort)
            for row in rows:
                urls: dict[str, str] = {}
                if row.status == MediaStatus.READY:
                    bucket = Bucket(variant_bucket(MediaPurpose(row.purpose)))
                    for name, variant in sorted(row.variants.items()):
                        urls[name] = await storage.presign_get(
                            bucket, variant["key"], ttl=EXPORT_LINK_TTL
                        )
                else:
                    urls["original"] = await storage.presign_get(
                        Bucket(row.bucket), row.object_key, ttl=EXPORT_LINK_TTL
                    )
                links.append({"media_id": row.id, "purpose": row.purpose, "urls": urls})
    return {"links": links, "links_valid_hours": EXPORT_LINK_TTL // timedelta(hours=1)}


export_section(
    "media",
    ExportTable(
        AssetRow,
        lambda user: AssetRow.owner_id == user,
        exclude=frozenset({"sha256", "upload_id", "etag"}),
    ),
    supplement=media_links,
)
