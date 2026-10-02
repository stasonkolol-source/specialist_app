"""Заявка ждёт проверки — модерации знать (ADR-0020 §2): событие-ссылка в той же транзакции,
содержимое конвейер прочтёт через фасад (адаптер цели `job`, moderation/infrastructure/targets)."""

from typing import Final

from app.modules.jobs.domain.job import Job
from app.platform.contracts.events.moderation import ModerationRequested
from app.platform.db.port import UnitOfWork

JOB: Final = "job"


def request_review(uow: UnitOfWork, job: Job, *, edit: bool) -> None:
    uow.add_event(
        ModerationRequested(
            entity_type=JOB,
            entity_id=job.id,
            author_id=job.client_id,
            edit=edit,
            occurred_at=job.updated_at,
        )
    )
