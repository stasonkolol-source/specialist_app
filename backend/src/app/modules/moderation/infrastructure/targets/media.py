"""Адаптер цели «фото» (план 6.7): фасад media для решений модератора по кейсам проверки фото.

Фото проверяет не конвейер текста (`auto_check`), а `moderation.check_image` по MediaReady —
поэтому `content` пуст. Решение по кейсу действует на файл: одобрение — фото проверено (скрытое
при P0 возвращается в публичный бакет), отказ — фото скрыто: API его не показывает, варианты
уходят в приватный бакет и хранятся там до очистки. Работы портфолио с одобренным фото, ждущие
проверки, снова идут на автопроверку — теперь их подпись (адаптер `portfolio`).
"""

from uuid import UUID

from app.modules.media.api import MediaModeration, ModerationVerdict
from app.modules.moderation.application.ports import ModerationTarget, TargetContent
from app.modules.specialists.api import SpecialistsApi
from app.platform.kernel.ids import MediaId


class MediaTarget(ModerationTarget):
    def __init__(self, media: MediaModeration, specialists: SpecialistsApi) -> None:
        self._media, self._specialists = media, specialists

    async def content(self, entity_id: UUID) -> TargetContent | None:  # noqa: ARG002
        return None  # фото проверяет moderation.check_image, а не конвейер текста

    async def publish(
        self,
        entity_id: UUID,
        *,
        version: int | None = None,  # noqa: ARG002 — у файла версий нет
    ) -> None:
        if await self._media.moderate(MediaId(entity_id), ModerationVerdict.APPROVED):
            await self._specialists.recheck_works(MediaId(entity_id))

    async def hide(self, entity_id: UUID, *, reason_code: str) -> None:  # noqa: ARG002
        await self._media.moderate(MediaId(entity_id), ModerationVerdict.REJECTED)
