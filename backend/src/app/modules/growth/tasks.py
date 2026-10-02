"""Задачи growth (ADR-0020 §3): подписки на события других модулей."""

from dishka import FromDishka

from app.modules.growth.application.ports import FORGET_ATTRIBUTION, RECORD_ATTRIBUTION
from app.modules.growth.application.use_cases.forget_attribution import (
    ForgetAttribution,
    ForgetAttributionCommand,
)
from app.modules.growth.application.use_cases.record_attribution import (
    RecordAttribution,
    RecordAttributionCommand,
)
from app.platform.contracts.events.identity import UserDeleted, UserRegistered
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


@subscriber(UserDeleted, FORGET_ATTRIBUTION)
async def forget_attribution(event: UserDeleted, forget: FromDishka[ForgetAttribution]) -> None:
    """Аккаунт удалён — его атрибуция тоже (§7.10)."""
    await forget(ForgetAttributionCommand(user_id=event.user_id))
