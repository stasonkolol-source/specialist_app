"""Уведомления, которые модуль ставит по имени задачи (DEVELOPMENT_PLAN 5.7, ARCHITECTURE §9.6).

Обычно notifications подписан на доменные события. Подписки на заявки — исключение: кому писать,
решает сам `jobs.match_alerts` (матчинг §9.6, блокировки, ограничения, лимиты частоты), и на
каждого получателя ставит `notifications.notify_job_matched` с ключом `job.matched:{job}:{user}` —
через JobQueue по имени задачи, не импортируя notifications (import-linter, ARCHITECTURE §5.4).
Подборку — так же, `notifications.notify_job_digest`. Здесь — общие для обеих сторон имена задач и
payload; обработчики объявлены в notifications/tasks.py.
"""

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.platform.kernel.ids import UserId
from app.platform.queue.port import TaskRef


@dataclass(frozen=True, slots=True, kw_only=True)
class JobMatchNotice:
    """Новая заявка по подписке — карточка B1 одному получателю."""

    job_id: UUID
    user_id: UserId
    alert_id: UUID
    """Подписка, по которой заявка подошла: её название в карточке и «Пауза подписки»."""
    distance_m: int | None = None
    """От точки подписки до смещённой точки заявки, шагом 100 м; у подписки без радиуса — нет."""


@dataclass(frozen=True, slots=True, kw_only=True)
class DigestAlert:
    alert_id: UUID
    job_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class JobDigestNotice:
    """Подборка заявок по подпискам «раз в день» одному получателю — в его час дайджеста."""

    user_id: UserId
    alerts: tuple[DigestAlert, ...]
    key: str
    """Подборка — ключ дедупликации уведомления (`job.digest:{user}:{key}`): повтор задачи
    второго сообщения не даёт."""


NOTIFY_JOB_MATCHED: Final = TaskRef(
    "notifications.notify_job_matched", JobMatchNotice, queue="notifications"
)
NOTIFY_JOB_DIGEST: Final = TaskRef(
    "notifications.notify_job_digest", JobDigestNotice, queue="notifications"
)
