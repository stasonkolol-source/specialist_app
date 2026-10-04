"""Подборки заявок «раз в день» (периодическая `jobs.alert_digests`, ежечасно; DEVELOPMENT_PLAN
5.7, ARCHITECTURE §12.3).

Каждый час: у кого ждут совпадения «подборкой» и чей час дайджеста пришёл (настройки
уведомлений, по умолчанию 09:00 по Белграду; порт DigestSchedule реализует notifications), тем —
`notifications.notify_job_digest` по имени задачи: заявки, сгруппированные по подпискам. Совпадения
отмечаются ушедшими в той же транзакции, ключ подборки — час отправки: повтор задачи второго
сообщения не даёт. Заодно удаляются совпадения старше месяца (лимит частоты их уже не считает).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Final
from uuid import UUID

from app.modules.jobs.api import DigestSchedule
from app.modules.jobs.application.ports import AlertMatches
from app.modules.jobs.domain.alert import AlertId
from app.platform.contracts.notices import NOTIFY_JOB_DIGEST, DigestAlert, JobDigestNotice
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId
from app.platform.queue.port import JobQueue

RETENTION: Final = timedelta(days=30)
DIGEST_JOBS: Final = 20
"""Заявок одной подписки в подборке: остальное — в ленте «по моим подпискам»."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SendAlertDigestsCommand:
    limit: int = 20_000
    """Ждущих совпадений за запуск, не больше: остальные — через час."""


class SendAlertDigests:
    def __init__(
        self,
        uow: UnitOfWork,
        matches: AlertMatches,
        schedule: DigestSchedule,
        queue: JobQueue,
        clock: Clock,
    ) -> None:
        self._uow, self._matches, self._schedule = uow, matches, schedule
        self._queue, self._clock = queue, clock

    async def __call__(self, cmd: SendAlertDigestsCommand) -> int:
        """Скольким людям ушла подборка."""
        now = self._clock.now()
        pending = await self._matches.pending_digests(limit=cmd.limit)
        by_user: dict[UserId, dict[AlertId, list[UUID]]] = defaultdict(lambda: defaultdict(list))
        for item in pending:
            by_user[item.user_id][item.alert_id].append(item.job_id)
        due = await self._schedule.due(by_user.keys(), now) if by_user else frozenset()
        key = now.strftime("%Y-%m-%dT%H")
        async with self._uow:
            for user_id in due:
                notice = JobDigestNotice(
                    user_id=user_id,
                    alerts=tuple(
                        DigestAlert(alert_id=alert_id, job_ids=tuple(jobs[-DIGEST_JOBS:]))
                        for alert_id, jobs in by_user[user_id].items()
                    ),
                    key=key,
                )
                await self._queue.enqueue(
                    NOTIFY_JOB_DIGEST, notice, dedup_key=f"job.digest:{user_id}:{key}"
                )
            await self._matches.mark_digested(due, now)
            await self._matches.purge(now - RETENTION)
        return len(due)
