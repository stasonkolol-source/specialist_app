"""Политики заявки (ARCHITECTURE §13.1: правило владения живёт в модуле, а не в роутере).

Чужая заявка для действий владельца — 404, как несуществующая: её существование не
раскрывается. Видимость: владелец видит свою в любом статусе, остальные (гость, исполнитель) —
только опубликованную; точную точку и адрес — никто, кроме выбранного исполнителя (6.x).
"""

from app.modules.jobs.domain.job import Job, JobStatus
from app.modules.jobs.errors import JobNotFoundError
from app.platform.kernel.ids import UserId

PUBLIC: frozenset[JobStatus] = frozenset({JobStatus.PUBLISHED})


def ensure_owner(job: Job, actor_id: UserId) -> None:
    """Действие владельца: чужая или удалённая заявка — 404."""
    if job.client_id != actor_id or job.deleted_at is not None:
        raise JobNotFoundError(job_id=job.id)


def is_owner(job: Job, viewer_id: UserId | None) -> bool:
    return viewer_id is not None and job.client_id == viewer_id


def can_view(*, client_id: UserId, status: JobStatus, viewer_id: UserId | None) -> bool:
    """Просмотр: владелец — свою в любом статусе, остальные — только опубликованную."""
    return (viewer_id is not None and client_id == viewer_id) or status in PUBLIC


def ensure_visible(job: Job, viewer_id: UserId | None) -> None:
    """То же для агрегата; удалённая не видна никому."""
    visible = can_view(client_id=job.client_id, status=job.status, viewer_id=viewer_id)
    if job.deleted_at is not None or not visible:
        raise JobNotFoundError(job_id=job.id)
