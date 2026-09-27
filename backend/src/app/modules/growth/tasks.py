"""Задачи growth (ADR-0020 §3): подписки на события других модулей."""

from dishka import FromDishka

from app.modules.growth.application.ports import RECORD_ATTRIBUTION
from app.modules.growth.application.use_cases.record_attribution import (
    RecordAttribution,
    RecordAttributionCommand,
)
from app.platform.contracts.events.identity import UserRegistered
from app.platform.queue.tasks import subscriber


@subscriber(UserRegistered, RECORD_ATTRIBUTION)
async def record_attribution(event: UserRegistered, record: FromDishka[RecordAttribution]) -> None:
    """Первое касание нового пользователя; повтор задачи ничего не меняет."""
    await record(
        RecordAttributionCommand(
            user_id=event.user_id,
            start_param=event.start_param,
            entry_point=event.entry_point,
            touched_at=event.occurred_at,
        )
    )
