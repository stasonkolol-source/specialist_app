"""Политики заявки (ARCHITECTURE §13.1: правило владения живёт в модуле, а не в роутере).

Чужая заявка для действий владельца — 404, как несуществующая: её существование не
раскрывается. Видимость: владелец видит свою в любом статусе, остальные (гость, исполнитель) —
только опубликованную, а прямой запрос (`visibility = direct`, 5.6) — только приглашённые.
Выбранный исполнитель (6.1a) видит заявку и «в работе», и завершённой — с точной точкой и
адресом; остальным их не показывают.
"""

from typing import Final

from app.modules.jobs.domain.job import Job, JobStatus, Visibility
from app.modules.jobs.errors import JobNotFoundError
from app.platform.kernel.ids import UserId

PUBLIC: frozenset[JobStatus] = frozenset({JobStatus.PUBLISHED})
CHOSEN: frozenset[JobStatus] = frozenset({JobStatus.ASSIGNED, JobStatus.COMPLETED})
"""Заявка после выбора исполнителя: её видят владелец и выбранный исполнитель (6.1a)."""

MAX_SAVED_JOBS: Final = 100
"""Сохранённых заявок у исполнителя (сердечко S15, S12): больше в списке не листают."""


def ensure_owner(job: Job, actor_id: UserId) -> None:
    """Действие владельца: чужая или удалённая заявка — 404."""
    if job.client_id != actor_id or job.deleted_at is not None:
        raise JobNotFoundError(job_id=job.id)


def is_owner(job: Job, viewer_id: UserId | None) -> bool:
    return viewer_id is not None and job.client_id == viewer_id


def can_view(
    *,
    client_id: UserId,
    status: JobStatus,
    viewer_id: UserId | None,
    visibility: Visibility = Visibility.PUBLIC,
    invited: bool = False,
    chosen: bool = False,
) -> bool:
    """Просмотр: владелец — свою в любом статусе, остальные — только опубликованную; прямой
    запрос — только приглашённый; после выбора — выбранный исполнитель (`chosen`)."""
    if viewer_id is not None and client_id == viewer_id:
        return True
    if chosen and status in CHOSEN:
        return True
    return status in PUBLIC and (visibility is Visibility.PUBLIC or invited)


def needs_chosen(*, client_id: UserId, status: JobStatus, viewer_id: UserId | None) -> bool:
    """Чтобы решить, видна ли заявка после выбора, нужно знать, выбран ли зритель."""
    return viewer_id is not None and viewer_id != client_id and status in CHOSEN


def needs_invite(*, client_id: UserId, visibility: Visibility, viewer_id: UserId | None) -> bool:
    """Чтобы решить, видна ли заявка, нужно знать, приглашён ли зритель: прямой запрос, смотрит
    не владелец."""
    return visibility is Visibility.DIRECT and viewer_id is not None and viewer_id != client_id


def ensure_visible(job: Job, viewer_id: UserId | None, *, invited: bool = False) -> None:
    """То же для агрегата; удалённая не видна никому."""
    visible = can_view(
        client_id=job.client_id,
        status=job.status,
        viewer_id=viewer_id,
        visibility=job.visibility,
        invited=invited,
    )
    if job.deleted_at is not None or not visible:
        raise JobNotFoundError(job_id=job.id)
