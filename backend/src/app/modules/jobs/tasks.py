"""Задачи jobs (ADR-0020 §3; DEVELOPMENT_PLAN 5.1; ARCHITECTURE §12).

- `jobs.forget_client` — UserDeleted: заявки удалённого аккаунта закрываются и удаляются,
  точная точка и адрес стираются (§7.10).
- `jobs.withdraw_performer_responses` — UserDeleted: его активные отклики отзываются, места на
  чужих заявках освобождаются (5.4).
- `jobs.release_blocked_responses` — UserBlocked: отклики одного на заявки другого освобождают
  места; заблокированному — «не выбран», без уведомления (MU-3).
- `jobs.announce_direct_request` — JobPublished прямого запроса: приглашённому — JobInvited (5.6).
- `jobs.reopen_job` — DealCancelled сделки из отклика: заявка снова открыта (6.1a).
- `jobs.complete_job` — DealCompleted сделки из отклика: заявка завершена (6.1a).
- `jobs.expire_jobs` — каждые 5 минут: опубликованные со сроком в прошлом — «истекла».
- `jobs.expiry_reminders` — каждые 15 минут: «Заявка закроется через 2 ч».
- `jobs.match_alerts` — JobPublished первой публикации публичной заявки: подписчикам — карточка
  B1 (`notifications.notify_job_matched` по имени задачи) или место в подборке (5.7, §9.6).
- `jobs.alert_digests` — ежечасно: подборки «раз в день» тем, чей час дайджеста пришёл (5.7).
- `jobs.forget_alerts` — UserDeleted: подписки и совпадения удалённого аккаунта (§7.10).
"""

from dishka import FromDishka

from app.modules.jobs.application.ports import (
    ANNOUNCE_DIRECT_REQUEST,
    COMPLETE_JOB,
    FORGET_ALERTS,
    FORGET_CLIENT_JOBS,
    MATCH_ALERTS,
    RELEASE_BLOCKED_RESPONSES,
    REOPEN_JOB,
    WITHDRAW_PERFORMER_RESPONSES,
)
from app.modules.jobs.application.use_cases.announce_direct_request import (
    AnnounceDirectRequest,
    AnnounceDirectRequestCommand,
)
from app.modules.jobs.application.use_cases.complete_job import CompleteJob, CompleteJobCommand
from app.modules.jobs.application.use_cases.expire_jobs import ExpireJobs, ExpireJobsCommand
from app.modules.jobs.application.use_cases.forget_alerts import (
    ForgetAlerts,
    ForgetAlertsCommand,
)
from app.modules.jobs.application.use_cases.forget_client_jobs import (
    ForgetClientJobs,
    ForgetClientJobsCommand,
)
from app.modules.jobs.application.use_cases.match_alerts import (
    MatchAlerts,
    MatchAlertsCommand,
)
from app.modules.jobs.application.use_cases.release_blocked_responses import (
    ReleaseBlockedResponses,
    ReleaseBlockedResponsesCommand,
)
from app.modules.jobs.application.use_cases.remind_expiring_jobs import (
    RemindExpiringJobs,
    RemindExpiringJobsCommand,
)
from app.modules.jobs.application.use_cases.reopen_job import ReopenJob, ReopenJobCommand
from app.modules.jobs.application.use_cases.send_alert_digests import (
    SendAlertDigests,
    SendAlertDigestsCommand,
)
from app.modules.jobs.application.use_cases.withdraw_performer_responses import (
    WithdrawPerformerResponses,
    WithdrawPerformerResponsesCommand,
)
from app.modules.jobs.domain.job import JobId
from app.modules.jobs.domain.response import ResponseId
from app.platform.contracts.events.deals import DealCancelled, DealCompleted
from app.platform.contracts.events.identity import UserBlocked, UserDeleted
from app.platform.contracts.events.jobs import JobPublished
from app.platform.queue.tasks import PeriodicRun, periodic, subscriber


@subscriber(UserDeleted, FORGET_CLIENT_JOBS)
async def forget_client(event: UserDeleted, forget: FromDishka[ForgetClientJobs]) -> None:
    await forget(ForgetClientJobsCommand(user_id=event.user_id))


@subscriber(UserDeleted, WITHDRAW_PERFORMER_RESPONSES)
async def withdraw_performer_responses(
    event: UserDeleted, withdraw: FromDishka[WithdrawPerformerResponses]
) -> None:
    await withdraw(WithdrawPerformerResponsesCommand(user_id=event.user_id))


@subscriber(UserBlocked, RELEASE_BLOCKED_RESPONSES)
async def release_blocked_responses(
    event: UserBlocked, release: FromDishka[ReleaseBlockedResponses]
) -> None:
    await release(
        ReleaseBlockedResponsesCommand(blocker_id=event.blocker_id, blocked_id=event.blocked_id)
    )


@subscriber(JobPublished, ANNOUNCE_DIRECT_REQUEST)
async def announce_direct_request(
    event: JobPublished, announce: FromDishka[AnnounceDirectRequest]
) -> None:
    if event.direct and not event.republished:
        await announce(AnnounceDirectRequestCommand(job_id=JobId(event.job_id)))


@subscriber(JobPublished, MATCH_ALERTS)
async def match_alerts(event: JobPublished, match: FromDishka[MatchAlerts]) -> None:
    if event.direct or event.republished:  # прямой запрос — приглашённым; повтор — не новость
        return
    await match(MatchAlertsCommand(job_id=JobId(event.job_id)))


@subscriber(UserDeleted, FORGET_ALERTS)
async def forget_alerts(event: UserDeleted, forget: FromDishka[ForgetAlerts]) -> None:
    await forget(ForgetAlertsCommand(user_id=event.user_id))


@subscriber(DealCancelled, REOPEN_JOB)
async def reopen_job(event: DealCancelled, reopen: FromDishka[ReopenJob]) -> None:
    if event.job_id is None or event.response_id is None:  # сделка не из отклика
        return
    await reopen(
        ReopenJobCommand(
            job_id=JobId(event.job_id),
            response_id=ResponseId(event.response_id),
            by_performer=event.cancelled_by == "performer",
        )
    )


@subscriber(DealCompleted, COMPLETE_JOB)
async def complete_job(event: DealCompleted, complete: FromDishka[CompleteJob]) -> None:
    if event.job_id is None or event.response_id is None:
        return
    await complete(
        CompleteJobCommand(job_id=JobId(event.job_id), response_id=ResponseId(event.response_id))
    )


@periodic("jobs.expire_jobs", cron="2-59/5 * * * *")  # со сдвигом от других «раз в 5 минут»
async def expire_jobs(run: PeriodicRun) -> None:
    async with run.container() as request:
        await (await request.get(ExpireJobs))(ExpireJobsCommand())


@periodic("jobs.expiry_reminders", cron="11,26,41,56 * * * *")
async def expiry_reminders(run: PeriodicRun) -> None:
    async with run.container() as request:
        await (await request.get(RemindExpiringJobs))(RemindExpiringJobsCommand())


@periodic("jobs.alert_digests", cron="1 * * * *")
async def alert_digests(run: PeriodicRun) -> None:
    """Ежечасно (§12.3: «ежечасно и в 09:00» — час дайджеста у каждого свой, по умолчанию 9)."""
    async with run.container() as request:
        await (await request.get(SendAlertDigests))(SendAlertDigestsCommand())
