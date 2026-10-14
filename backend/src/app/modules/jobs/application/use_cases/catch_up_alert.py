"""Досыл новой подписке (задача `jobs.catch_up_alert` по AlertCreated; DEVELOPMENT_PLAN 5.7).

Подписка ловит только заявки, опубликованные после неё: исполнитель, который подписался (или за
которого подписку завёл профиль), в тихий день не видит ничего и решает, что заявок нет.
Поэтому открытые публичные заявки трёх суток до создания подписки (CATCH_UP_WINDOW), которые
подходят ей (SQL §9.6), уходят ему как обычные: свежие первыми, карточками B1 в лимит частоты
(10 в час, 40 в сутки — с учётом уже полученных), сверх и подписке «подборкой» — в подборку
`jobs.alert_digests`.
Тихие часы — у `notifications.notify_job_matched`, как у любой карточки. Не досылаются: заявки
тех, с кем у подписчика блокировка (4.7), на которые он откликнулся или скрыл, и те, о которых он
уже получал карточку по другой подписке; под санкцией на отклик — ничего. Подписку выключили или
удалили, пока задача ждала, — ничего. Повтор задачи второй карточки не даёт: набор досыла — не
больше CATCH_UP_LIMIT свежих заявок окна, он не зависит от времени запуска, а совпадения помнят
пары «заявка — человек».
"""

from dataclasses import dataclass

from app.modules.identity.api import Action, IdentityApi
from app.modules.jobs.application.alerts import (
    CATCH_UP_LIMIT,
    CATCH_UP_WINDOW,
    route_catch_up,
)
from app.modules.jobs.application.ports import AlertMatches, JobAlerts, JobQueries
from app.modules.jobs.application.use_cases.match_alerts import MATCH_PRIORITY
from app.modules.jobs.domain.alert import AlertDelivery, AlertId
from app.platform.contracts.notices import NOTIFY_JOB_MATCHED, JobMatchNotice
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.queue.port import JobQueue


@dataclass(frozen=True, slots=True, kw_only=True)
class CatchUpAlertCommand:
    alert_id: AlertId


class CatchUpAlert:
    def __init__(
        self,
        uow: UnitOfWork,
        alerts: JobAlerts,
        matches: AlertMatches,
        queries: JobQueries,
        identity: IdentityApi,
        queue: JobQueue,
        clock: Clock,
    ) -> None:
        self._uow, self._alerts, self._matches, self._queries = uow, alerts, matches, queries
        self._identity, self._queue, self._clock = identity, queue, clock

    async def __call__(self, cmd: CatchUpAlertCommand) -> int:
        """Сколько заявок ушло подписчику (сразу и подборкой)."""
        alert = await self._alerts.get(cmd.alert_id)
        now = self._clock.now()
        if alert is None or not alert.receives(now):
            return 0
        if await self._identity.barred({alert.user_id}, Action.RESPOND):
            return 0
        # окно — от создания подписки: заявки после него ловит обычная рассылка (`match_alerts`),
        # а набор досыла от времени запуска не зависит — повтор задачи новых заявок не найдёт
        candidates = await self._matches.recent_jobs(
            alert.id,
            since=alert.created_at - CATCH_UP_WINDOW,
            until=alert.created_at,
            now=now,
            limit=CATCH_UP_LIMIT,
        )
        if not candidates:
            return 0
        hidden = await self._identity.blocked_ids(alert.user_id)
        skipped = await self._queries.skipped(
            [candidate.job_id for candidate in candidates], alert.user_id
        )
        wanted = [
            candidate
            for candidate in candidates
            if candidate.client_id not in hidden and candidate.job_id not in skipped
        ]
        if not wanted:
            return 0
        sent = 0
        async with self._uow:
            recent = await self._matches.recent_cards([alert.user_id], now)
            for job_id, match in route_catch_up(alert, wanted, recent=recent.get(alert.user_id)):
                if not await self._matches.record(job_id, [match], now):
                    continue  # повтор задачи: карточка этой заявки уже ушла
                await self._matches.add_notified(job_id, 1)
                sent += 1
                if match.delivery is not AlertDelivery.INSTANT:
                    continue
                await self._queue.enqueue(
                    NOTIFY_JOB_MATCHED,
                    JobMatchNotice(
                        job_id=job_id,
                        user_id=alert.user_id,
                        alert_id=alert.id,
                        distance_m=match.distance_m,
                    ),
                    dedup_key=f"job.matched:{job_id}:{alert.user_id}",
                    priority=MATCH_PRIORITY,
                )
        return sent
