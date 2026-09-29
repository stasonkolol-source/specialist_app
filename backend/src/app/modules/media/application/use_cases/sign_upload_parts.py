"""Новые ссылки на загрузку (POST /media/uploads/{id}/parts): после обрыва или истечения.

Presigned-ссылка живёт 10 минут; просроченная — 400 у Garage и 403 у R2, клиент просит
новую на те же части (docs/spikes/0.24-webview-upload.md). Без номеров частей — все.
"""

from dataclasses import dataclass

from app.modules.media.application.dto import UploadPlan
from app.modules.media.application.ports import MediaRepository
from app.modules.media.application.uploads import upload_plan
from app.platform.kernel.ids import MediaId, UserId
from app.platform.storage.port import StoragePort


@dataclass(frozen=True, slots=True, kw_only=True)
class SignUploadPartsCommand:
    owner_id: UserId
    media_id: MediaId
    part_numbers: tuple[int, ...] | None = None


class SignUploadParts:
    def __init__(self, assets: MediaRepository, storage: StoragePort) -> None:
        self._assets, self._storage = assets, storage

    async def __call__(self, cmd: SignUploadPartsCommand) -> UploadPlan:
        asset = await self._assets.get(cmd.owner_id, cmd.media_id)
        asset.ensure_pending()
        return await upload_plan(self._storage, asset, cmd.part_numbers)
