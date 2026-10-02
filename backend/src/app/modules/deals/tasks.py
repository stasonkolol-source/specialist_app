"""Задачи deals (ADR-0020 §3).

- `deals.cancel_user_deals` — UserDeleted: идущие сделки и предложения удалённого аккаунта
  отменяются (6.1a). Задачи сроков и напоминаний — 6.1b.
"""

from dishka import FromDishka

from app.modules.deals.application.ports import CANCEL_USER_DEALS
from app.modules.deals.application.use_cases.cancel_user_deals import (
    CancelUserDeals,
    CancelUserDealsCommand,
)
from app.platform.contracts.events.identity import UserDeleted
from app.platform.queue.tasks import subscriber


@subscriber(UserDeleted, CANCEL_USER_DEALS)
async def cancel_user_deals(event: UserDeleted, cancel: FromDishka[CancelUserDeals]) -> None:
    await cancel(CancelUserDealsCommand(user_id=event.user_id))
