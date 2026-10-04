"""Срок хранения заявок и откликов (правило `jobs.jobs_and_responses` ночной
`platform.retention_sweep`; ARCHITECTURE §7.10, DEVELOPMENT_PLAN 2.12b).

Закрытая, выполненная, истёкшая или снятая заявка удаляется через 24 месяца после закрытия
(истёкшая — после срока), отклонённая модерацией — через 6 месяцев (окно апелляции): вместе с
откликами, фото, историей статусов, приглашениями, скрытыми и сохранёнными. Не удаляется, пока:
- о заявке или её отклике открыт кейс модерации (legal hold, RetentionHold);
- на неё ссылается переписка (messaging, JobReferences): переписка живёт 12 месяцев после
  последнего сообщения и уходит раньше, но разговор по старой заявке мог продолжиться.
Удержанные проверяются снова следующей ночью. Страница — одна транзакция.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from app.modules.jobs.api import JobReferences
from app.modules.jobs.application.ports import JobRetention
from app.modules.jobs.domain.job import JobId
from app.modules.media.api import MediaApi
from app.platform.db.port import UnitOfWork
from app.platform.privacy.port import HoldKind, RetentionHold

KEEP_CLOSED: Final = timedelta(days=730)
"""24 месяца после закрытия (§7.10)."""
KEEP_REJECTED: Final = timedelta(days=182)
"""6 месяцев после отказа модерации: окно апелляции (§7.10, §14.4)."""
BATCH: Final = 200


@dataclass(frozen=True, slots=True, kw_only=True)
class PurgeExpiredJobsCommand:
    now: datetime
    limit: int = BATCH


class PurgeExpiredJobs:
    def __init__(
        self,
        uow: UnitOfWork,
        retention: JobRetention,
        hold: RetentionHold,
        references: JobReferences,
        media: MediaApi,
    ) -> None:
        self._uow, self._retention, self._hold = uow, retention, hold
        self._references, self._media = references, media

    async def __call__(self, cmd: PurgeExpiredJobsCommand) -> int:
        """Сколько заявок удалено."""
        purged = 0
        cursor: JobId | None = None
        while True:
            async with self._uow:
                page = await self._retention.expired(
                    closed_before=cmd.now - KEEP_CLOSED,
                    rejected_before=cmd.now - KEEP_REJECTED,
                    after=cursor,
                    limit=cmd.limit,
                )
                free = await self._free(page)
                for owner_id, media_id in await self._retention.photos(free):
                    await self._media.discard(owner_id, media_id)
                await self._retention.purge(free)
            purged += len(free)
            if len(page) < cmd.limit:
                return purged
            cursor = page[-1]

    async def _free(self, job_ids: list[JobId]) -> list[JobId]:
        if not job_ids:
            return []
        held: set[UUID] = set(await self._hold.held(HoldKind.JOB, job_ids))
        responses = await self._retention.responses(job_ids)
        held_responses = await self._hold.held(HoldKind.RESPONSE, list(responses))
        held |= {
            job_id for response_id, job_id in responses.items() if response_id in held_responses
        }
        referenced = await self._references.referenced([*job_ids, *responses])
        held |= {job_id for job_id in job_ids if job_id in referenced}
        held |= {job_id for response_id, job_id in responses.items() if response_id in referenced}
        return [job_id for job_id in job_ids if job_id not in held]
