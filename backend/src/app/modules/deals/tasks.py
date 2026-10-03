"""Задачи deals (ADR-0020 §3).

- `deals.cancel_user_deals` — UserDeleted: идущие сделки и предложения удалённого аккаунта
  отменяются (6.1a).
- Сроки (6.1b, §12.3): `deals.reminders` (каждые 15 минут) — за 2 ч до времени сделки;
  `deals.completion_prompts` (каждые 15 минут) — «Работа выполнена?» после него;
  `deals.expire_proposed` (каждые 15 минут) — «Договорились» без ответа 72 ч;
  `deals.auto_complete` (ежечасно) — одна сторона отметила «выполнено», 72 ч без возражений.
- `deals.dispute_response_sla` (каждые 30 минут, 6.1c; `disputes.response_sla` §12.3) — вторая
  сторона не ответила на спор за 48 ч: «нет ответа», модерация помечает кейс.
"""

from dishka import FromDishka

from app.modules.deals.application.ports import CANCEL_USER_DEALS, DealSweep
from app.modules.deals.application.use_cases.cancel_user_deals import (
    CancelUserDeals,
    CancelUserDealsCommand,
)
from app.modules.deals.application.use_cases.sweep_deals import SweepDeals, SweepDealsCommand
from app.modules.deals.application.use_cases.sweep_disputes import (
    SweepDisputes,
    SweepDisputesCommand,
)
from app.platform.contracts.events.identity import UserDeleted
from app.platform.queue.tasks import PeriodicRun, periodic, subscriber


@subscriber(UserDeleted, CANCEL_USER_DEALS)
async def cancel_user_deals(event: UserDeleted, cancel: FromDishka[CancelUserDeals]) -> None:
    await cancel(CancelUserDealsCommand(user_id=event.user_id))


@periodic("deals.reminders", cron="3-59/15 * * * *")  # со сдвигом от других «раз в 15 минут»
async def reminders(run: PeriodicRun) -> None:
    await _sweep(run, DealSweep.REMIND)


@periodic("deals.completion_prompts", cron="7-59/15 * * * *")
async def completion_prompts(run: PeriodicRun) -> None:
    await _sweep(run, DealSweep.PROMPT)


@periodic("deals.expire_proposed", cron="12-59/15 * * * *")
async def expire_proposed(run: PeriodicRun) -> None:
    await _sweep(run, DealSweep.EXPIRE_PROPOSALS)


@periodic("deals.auto_complete", cron="27 * * * *")
async def auto_complete(run: PeriodicRun) -> None:
    await _sweep(run, DealSweep.AUTO_COMPLETE)


@periodic("deals.dispute_response_sla", cron="14,44 * * * *")
async def dispute_response_sla(run: PeriodicRun) -> None:
    async with run.container() as request:
        await (await request.get(SweepDisputes))(SweepDisputesCommand())


async def _sweep(run: PeriodicRun, sweep: DealSweep) -> None:
    async with run.container() as request:
        await (await request.get(SweepDeals))(SweepDealsCommand(sweep=sweep))
