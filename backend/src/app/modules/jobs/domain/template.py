"""Шаблон отклика (DEVELOPMENT_PLAN 5.5; ARCHITECTURE §8.5): готовое сообщение, цена и «когда
смогу» для отклика в пару тапов (S16) и кнопками в уведомлении бота (5.7). У исполнителя — не
больше двух шаблонов; первый по порядку — основной: S16 подставляет его сразу.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final, NewType
from uuid import UUID

from app.modules.jobs.domain.response import Offer
from app.modules.jobs.errors import InvalidTemplateError
from app.platform.kernel.ids import UserId

TemplateId = NewType("TemplateId", UUID)

MAX_TEMPLATES: Final = 2
"""Шаблонов у исполнителя: оба — кнопками в уведомлении бота."""
MAX_TEMPLATE_TITLE: Final = 40


def template_title(value: str) -> str:
    """Название шаблона — «Могу сегодня»: от 1 до 40 знаков после обрезки пробелов."""
    title = value.strip()
    if not 1 <= len(title) <= MAX_TEMPLATE_TITLE:
        raise InvalidTemplateError(field="title", reason="length")
    return title


@dataclass(frozen=True, slots=True, kw_only=True)
class ResponseTemplate:
    id: TemplateId
    user_id: UserId
    title: str
    offer: Offer
    position: int
    """0 — основной."""
    created_at: datetime
    updated_at: datetime

    @property
    def primary(self) -> bool:
        return self.position == 0
