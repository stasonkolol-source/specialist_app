"""Задачи messaging (ADR-0020 §3).

- `messaging.forget_messages` — UserDeleted: текст сообщений удалённого аккаунта стирается
  (§7.10, 6.3a).
- `messaging.record_deal_agreed` — DealAgreed: «Договорились» в ленте диалога сделки (или диалога
  по выбранному отклику), контакты в нём открываются (6.3b).
- `messaging.record_deal_cancelled` — DealCancelled: предложение отклонено, истекло или сделку
  отменили — в ленте диалога (6.3b).
"""

from dishka import FromDishka

from app.modules.messaging.application.ports import (
    FORGET_MESSAGES,
    RECORD_DEAL_AGREED,
    RECORD_DEAL_CANCELLED,
)
from app.modules.messaging.application.use_cases.forget_messages import (
    ForgetMessages,
    ForgetMessagesCommand,
)
from app.modules.messaging.application.use_cases.record_deal_event import (
    RecordDealEvent,
    RecordDealEventCommand,
)
from app.modules.messaging.domain.message import SystemEvent
from app.platform.contracts.events.deals import DealAgreed, DealCancelled
from app.platform.contracts.events.identity import UserDeleted
from app.platform.queue.tasks import subscriber


@subscriber(UserDeleted, FORGET_MESSAGES)
async def forget_messages(event: UserDeleted, forget: FromDishka[ForgetMessages]) -> None:
    await forget(ForgetMessagesCommand(user_id=event.user_id))


@subscriber(DealAgreed, RECORD_DEAL_AGREED)
async def record_deal_agreed(event: DealAgreed, record: FromDishka[RecordDealEvent]) -> None:
    await record(
        RecordDealEventCommand(
            deal_id=event.deal_id,
            response_id=event.response_id,
            event=SystemEvent.DEAL_AGREED,
            at=event.occurred_at,
        )
    )


@subscriber(DealCancelled, RECORD_DEAL_CANCELLED)
async def record_deal_cancelled(event: DealCancelled, record: FromDishka[RecordDealEvent]) -> None:
    await record(
        RecordDealEventCommand(
            deal_id=event.deal_id,
            response_id=event.response_id,
            event=SystemEvent.DEAL_CANCELLED,
            at=event.occurred_at,
            details={"by": event.cancelled_by, "reason": event.reason},
        )
    )
