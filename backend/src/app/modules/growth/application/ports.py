"""Порты модуля growth (ADR-0020 §3, §5)."""

from datetime import datetime
from typing import Final, Protocol

from app.modules.growth.domain.attribution import FirstTouch
from app.platform.contracts.events.identity import UserRegistered
from app.platform.kernel.ids import UserId
from app.platform.queue.port import TaskRef


class AttributionRepository(Protocol):
    """Атрибуция — простая запись (ADR-0020 §5): правило одно — первое касание."""

    async def record_first_touch(self, user_id: UserId, touch: FirstTouch, *, at: datetime) -> bool:
        """Записать первое касание; запись уже есть — ничего не меняет.

        True — записано сейчас. UserNotFoundError — пользователя нет. Нужен активный UoW.
        """
        ...


RECORD_ATTRIBUTION: Final = TaskRef("growth.record_attribution", UserRegistered)
"""Подписчик UserRegistered: первое касание нового пользователя."""
