"""Время ответа специалистов (periodic `search.response_time_stats`, раз в час; DEVELOPMENT_PLAN
6.3b): медиана от первого сообщения клиента до первого ответа специалиста в диалогах за 30 дней
(переписка считает её сама, фасад messaging) → `response_time_minutes` строки read-model.
«Обычно отвечает за …» на S08 — при пяти и больше диалогах с ответом; у кого их стало меньше,
значение снимается.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from app.modules.messaging.api import MessagingApi
from app.modules.search.application.ports import SpecialistIndex
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock

WINDOW: Final = timedelta(days=30)
MIN_CONVERSATIONS: Final = 5
"""Меньше пяти диалогов с ответом — медиана случайна: на карточке её нет."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RefreshResponseTimesCommand:
    pass


class RefreshResponseTimes:
    def __init__(
        self, uow: UnitOfWork, index: SpecialistIndex, messaging: MessagingApi, clock: Clock
    ) -> None:
        self._uow, self._index, self._messaging, self._clock = uow, index, messaging, clock

    async def __call__(self, cmd: RefreshResponseTimesCommand) -> int:  # noqa: ARG002 — без параметров
        """Сколько специалистов с медианой."""
        times = await self._messaging.response_times(
            since=self._clock.now() - WINDOW, min_conversations=MIN_CONVERSATIONS
        )
        async with self._uow:
            await self._index.set_response_times({t.performer_id: t.minutes for t in times})
        return len(times)
