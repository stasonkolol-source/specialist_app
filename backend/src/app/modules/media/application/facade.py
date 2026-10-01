"""Реализация MediaApi (ADR-0020 §6): файлы для модулей выше по DAG — портфолио, фото профиля."""

from collections.abc import Collection

from app.modules.media.api import MediaApi, MediaRef, MediaVariantRef
from app.modules.media.application.dto import MediaView
from app.modules.media.application.ports import MediaQuery
from app.modules.media.application.queries import MediaQueries
from app.modules.media.application.use_cases.delete_media import DeleteMedia, DeleteMediaCommand
from app.modules.media.domain.asset import MediaStatus
from app.modules.media.domain.policy import MediaPurpose
from app.modules.media.errors import MediaNotFoundError, MediaStateError
from app.platform.kernel.ids import MediaId, UserId

ATTACHABLE = frozenset({MediaStatus.UPLOADED, MediaStatus.PROCESSING, MediaStatus.READY})
"""Прикрепить можно загруженный файл — даже пока он обрабатывается: экран ждёт вариантов."""


class MediaFacade(MediaApi):
    def __init__(self, query: MediaQuery, queries: MediaQueries, delete: DeleteMedia) -> None:
        self._query, self._queries, self._delete = query, queries, delete

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

    async def discard(self, owner_id: UserId, media_id: MediaId) -> None:
        try:
            await self._delete(DeleteMediaCommand(owner_id=owner_id, media_id=media_id))
        except MediaNotFoundError:
            return


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
