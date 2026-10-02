"""Контракт модуля jobs для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из jobs только этот файл.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.platform.kernel.ids import MediaId, UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class JobForReview:
    """Заявка для конвейера модерации (адаптер цели `job`, §14.1)."""

    client_id: UserId
    text: str
    """Заголовок и описание — то, что увидят исполнители."""
    version: int
    media_ids: tuple[MediaId, ...]
    risk_level: int
    """Риск категории: `≥ 1` — заявку проверяет человек (P2)."""


class JobsApi(Protocol):
    async def job_for_review(self, job_id: UUID) -> JobForReview | None:
        """Заявка на проверке или опубликованная (выборочная проверка после публикации);
        None — нет такой, удалена или проверять нечего."""
        ...

    async def approve_job(self, job_id: UUID, *, version: int | None) -> None:
        """Проверка пройдена — в транзакции вызывающего: ждавшая проверки публикуется; другая
        версия (клиент успел поправить) или статус — ничего."""
        ...

    async def reject_job(self, job_id: UUID, *, reason_code: str) -> None:
        """Нарушение — в транзакции вызывающего: ждавшая проверки отклоняется (клиент
        исправит), опубликованная снимается."""
        ...
