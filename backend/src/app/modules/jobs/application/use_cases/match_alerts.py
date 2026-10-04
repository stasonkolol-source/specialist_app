"""Новая заявка — подписчикам (задача `jobs.match_alerts` по JobPublished; DEVELOPMENT_PLAN 5.7,
ARCHITECTURE §9.6, §11.2).

Только первая публикация публичной заявки (продление и правка — не новость, прямой запрос видят
одни приглашённые): подписки, которым она подходит (SQL §9.6), без тех, с кем у клиента
блокировка в любую сторону (4.7), удалённых и тех, кому санкция запрещает откликаться. По
карточке на человека; сверх лимита частоты — подборкой (application/alerts.py). В одной
транзакции: совпадения (повтор задачи пропускает уже записанных), `notified_count` заявки и на
каждого «сразу» — `notifications.notify_job_matched` по имени задачи, ключ
`job.matched:{job}:{user}`: jobs не импортирует notifications (import-linter). «Подборкой» ждут
`jobs.alert_digests`. В аналитику — одно событие AlertsMatched на заявку.
"""

from dataclasses import dataclass
from typing import Final

from app.modules.identity.api import Action, IdentityApi
from app.modules.jobs.application.alerts import route_matches
from app.modules.jobs.application.ports import AlertMatches, JobQueries
from app.modules.jobs.domain.alert import AlertDelivery
from app.modules.jobs.domain.job import JobId, JobStatus, Visibility
from app.platform.contracts.events.jobs import AlertsMatched
from app.platform.contracts.notices import NOTIFY_JOB_MATCHED, JobMatchNotice
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.queue.port import JobQueue

MATCH_PRIORITY: Final = -1
"""Рассылка по подпискам — после уведомлений из событий (отклик, сообщение, сделка): сотни
карточек одной заявки не задерживают в очереди сообщение чата (§11.2, приоритеты)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class MatchAlertsCommand:
    job_id: JobId


class MatchAlerts:
    def __init__(
        self,
        uow: UnitOfWork,
        queries: JobQueries,
        matches: AlertMatches,
        identity: IdentityApi,
        queue: JobQueue,
        clock: Clock,
    ) -> None:
        self._uow, self._queries, self._matches = uow, queries, matches
        self._identity, self._queue, self._clock = identity, queue, clock

    async def __call__(self, cmd: MatchAlertsCommand) -> int:
        """Скольким подписчикам заявка ушла (сразу и подборкой) в этот запуск."""
        job = await self._queries.view(cmd.job_id)
        if job is None or job.status is not JobStatus.PUBLISHED:
            return 0  # пока задача ждала, заявку закрыли или сняли
        if job.visibility is not Visibility.PUBLIC:
            return 0
        now = self._clock.now()
        candidates = await self._matches.candidates(job.id, now)
        if not candidates:
            return 0
        users = {candidate.user_id for candidate in candidates}
        excluded = set(await self._identity.blocked_ids(job.client_id)) & users
        excluded |= await self._identity.barred(users - excluded, Action.RESPOND)
        async with self._uow:
            recent = await self._matches.recent_cards(users - excluded, now)
            routed = route_matches(candidates, excluded=excluded, recent=recent)
            recorded = await self._matches.record(job.id, routed, now)
            if not recorded:
                return 0
            await self._matches.add_notified(job.id, len(recorded))
            instant = [match for match in recorded if match.delivery is AlertDelivery.INSTANT]
            for match in instant:
                await self._queue.enqueue(
                    NOTIFY_JOB_MATCHED,
                    JobMatchNotice(
                        job_id=job.id,
                        user_id=match.user_id,
                        alert_id=match.alert_id,
                        distance_m=match.distance_m,
                    ),
                    dedup_key=f"job.matched:{job.id}:{match.user_id}",
                    priority=MATCH_PRIORITY,
                )
            self._uow.add_event(
                AlertsMatched(
                    job_id=job.id,
                    client_id=job.client_id,
                    category_id=job.category_id,
                    city_id=job.city_id,
                    urgency=job.urgency.value,
                    instant=len(instant),
                    digest=len(recorded) - len(instant),
                    occurred_at=now,
                )
            )
        return len(recorded)
