"""Фото заявки для экранов: вариант нужного размера из media — превью ленты (thumb) или фото
карточки S15 (md). Пока файл обрабатывается или обработка не прошла, фото не показывается."""

from collections.abc import Mapping, Sequence
from typing import Final

from app.modules.jobs.application.feed import Photo
from app.modules.media.api import MediaRef
from app.platform.kernel.ids import MediaId

THUMB: Final = "thumb"
"""320 px — карточка ленты."""
LARGE: Final = "md"
"""800 px — карточка заявки S15."""
READY: Final = "ready"


def photos_of(
    media_ids: Sequence[MediaId], refs: Mapping[MediaId, MediaRef], variant: str
) -> tuple[Photo, ...]:
    photos: list[Photo] = []
    for media_id in media_ids:
        ref = refs.get(media_id)
        if ref is None or ref.status != READY:
            continue
        found = next((v for v in ref.variants if v.name == variant), None)
        if found is not None:
            photos.append(
                Photo(
                    url=found.url,
                    width=found.width,
                    height=found.height,
                    placeholder=ref.placeholder,
                )
            )
    return tuple(photos)
