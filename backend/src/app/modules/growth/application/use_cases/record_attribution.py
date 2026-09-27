"""Первое касание нового пользователя (ARCHITECTURE §11.4, DEVELOPMENT_PLAN 1.4b).

Вызывает подписчик `UserRegistered`: код deep link регистрации разбирается кодеком и
записывается один раз. Повтор задачи и любое следующее касание запись не меняют.
"""

from dataclasses import dataclass
from datetime import datetime

import structlog

from app.modules.growth.application.ports import AttributionRepository
from app.modules.growth.domain.attribution import FirstTouch
from app.platform.contracts.events.identity import EntryPoint
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordAttributionCommand:
    user_id: UserId
    start_param: str | None
    entry_point: EntryPoint | None
    touched_at: datetime
    """Время касания — момент регистрации, а не выполнения задачи."""


class RecordAttribution:
    def __init__(self, uow: UnitOfWork, attributions: AttributionRepository) -> None:
        self._uow, self._attributions = uow, attributions

    async def __call__(self, cmd: RecordAttributionCommand) -> bool:
        """True — записано сейчас; False — у пользователя уже есть первое касание."""
        touch = FirstTouch.of(cmd.start_param, entry_point=cmd.entry_point)
        async with self._uow:
            recorded = await self._attributions.record_first_touch(
                cmd.user_id, touch, at=cmd.touched_at
            )
        if recorded:
            log.info(
                "attribution_recorded",
                user_id=str(cmd.user_id),
                source=touch.source.value,
                has_ref=touch.referral_code is not None,
            )
        return recorded
