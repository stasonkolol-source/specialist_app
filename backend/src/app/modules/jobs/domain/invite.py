"""Приглашение в заявку (DEVELOPMENT_PLAN 5.6; ARCHITECTURE §8.5): клиент зовёт специалиста из
каталога в опубликованную заявку (S21, S23) или отправляет ему прямой запрос — заявку, которую
видит только он (`visibility = direct`, S08, S09). Приглашённый видит прямую заявку и может на
неё откликнуться.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from app.modules.jobs.domain.job import JobId
from app.platform.kernel.ids import UserId

MAX_INVITES: Final = 10
"""Приглашённых в одну заявку: больше — уже рассылка, а не выбор."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Invite:
    job_id: JobId
    profile_id: UUID
    performer_id: UserId
    """Владелец профиля: видит прямую заявку и получает уведомление."""
    invited_at: datetime
