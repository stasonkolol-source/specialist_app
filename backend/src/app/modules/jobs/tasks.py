"""Задачи jobs (ADR-0020 §3; DEVELOPMENT_PLAN 5.1; ARCHITECTURE §12).

- `jobs.forget_client` — UserDeleted: заявки удалённого аккаунта закрываются и удаляются,
  точная точка и адрес стираются (§7.10).
- `jobs.expire_jobs` — каждые 5 минут: опубликованные со сроком в прошлом — «истекла».
- `jobs.expiry_reminders` — каждые 15 минут: «Заявка закроется через 2 ч».
"""

from dishka import FromDishka

from app.modules.jobs.application.ports import FORGET_CLIENT_JOBS
from app.modules.jobs.application.use_cases.expire_jobs import ExpireJobs, ExpireJobsCommand
from app.modules.jobs.application.use_cases.forget_client_jobs import (
    ForgetClientJobs,
    ForgetClientJobsCommand,
)
from app.modules.jobs.application.use_cases.remind_expiring_jobs import (
    RemindExpiringJobs,
    RemindExpiringJobsCommand,
)
from app.platform.contracts.events.identity import UserDeleted
from app.platform.queue.tasks import PeriodicRun, periodic, subscriber


@subscriber(UserDeleted, FORGET_CLIENT_JOBS)
async def forget_client(event: UserDeleted, forget: FromDishka[ForgetClientJobs]) -> None:
    await forget(ForgetClientJobsCommand(user_id=event.user_id))


@periodic("jobs.expire_jobs", cron="2-59/5 * * * *")  # со сдвигом от других «раз в 5 минут»
async def expire_jobs(run: PeriodicRun) -> None:
    async with run.container() as request:
        await (await request.get(ExpireJobs))(ExpireJobsCommand())


@periodic("jobs.expiry_reminders", cron="11,26,41,56 * * * *")
async def expiry_reminders(run: PeriodicRun) -> None:
    async with run.container() as request:
        await (await request.get(RemindExpiringJobs))(RemindExpiringJobsCommand())
