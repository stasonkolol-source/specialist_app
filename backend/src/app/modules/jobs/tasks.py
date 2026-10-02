"""Задачи jobs (ADR-0020 §3; DEVELOPMENT_PLAN 5.1).

- `jobs.forget_client` — UserDeleted: заявки удалённого аккаунта закрываются и удаляются,
  точная точка и адрес стираются (§7.10).
"""

from dishka import FromDishka

from app.modules.jobs.application.ports import FORGET_CLIENT_JOBS
from app.modules.jobs.application.use_cases.forget_client_jobs import (
    ForgetClientJobs,
    ForgetClientJobsCommand,
)
from app.platform.contracts.events.identity import UserDeleted
from app.platform.queue.tasks import subscriber


@subscriber(UserDeleted, FORGET_CLIENT_JOBS)
async def forget_client(event: UserDeleted, forget: FromDishka[ForgetClientJobs]) -> None:
    await forget(ForgetClientJobsCommand(user_id=event.user_id))
