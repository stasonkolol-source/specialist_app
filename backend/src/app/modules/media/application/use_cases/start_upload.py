"""Начать загрузку (POST /media/uploads, ARCHITECTURE §10.2, ADR-0007).

Проверка назначения, типа и размера (§10.1), запись `pending_upload` и ссылки на загрузку:
presigned PUT на 10 минут или план multipart для видео больше 50 MB. Лимиты «50 загрузок в
час, 1 GB в сутки» считает HTTP-слой (антиспам, §13.3), размер здесь уже проверен.
"""

from dataclasses import dataclass

from app.modules.media.application.dto import UploadPlan
from app.modules.media.application.ports import MediaRepository
from app.modules.media.application.uploads import upload_plan
from app.modules.media.domain.asset import INCOMING_BUCKET, MediaAsset, object_key
from app.modules.media.domain.policy import MediaPurpose, upload_rule
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import MediaId, UserId, new_id
from app.platform.storage.port import Bucket, StoragePort


@dataclass(frozen=True, slots=True, kw_only=True)
class StartUploadCommand:
    owner_id: UserId
    purpose: MediaPurpose
    mime_type: str
    size_bytes: int


class StartUpload:
    def __init__(
        self, uow: UnitOfWork, assets: MediaRepository, storage: StoragePort, clock: Clock
    ) -> None:
        self._uow, self._assets, self._storage, self._clock = uow, assets, storage, clock

    async def __call__(self, cmd: StartUploadCommand) -> UploadPlan:
        rule = upload_rule(cmd.purpose, cmd.mime_type, cmd.size_bytes)
        media_id = MediaId(new_id())
        now = self._clock.now()
        upload_id = None
        if rule.multipart:  # сетевой вызов — до транзакции; сирота в incoming уйдёт по lifecycle
            upload_id = await self._storage.start_multipart(
                Bucket(INCOMING_BUCKET),
                object_key(cmd.purpose, media_id, now),
                content_type=cmd.mime_type,
            )
        asset = MediaAsset.start(
            media_id=media_id,
            owner_id=cmd.owner_id,
            kind=rule.kind,
            purpose=cmd.purpose,
            mime_type=cmd.mime_type,
            size_bytes=cmd.size_bytes,
            now=now,
            upload_id=upload_id,
        )
        async with self._uow:
            await self._assets.add(asset)
        return await upload_plan(self._storage, asset)
