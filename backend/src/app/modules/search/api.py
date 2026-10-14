"""Контракт модуля search для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из search только этот файл.
"""

from collections.abc import Collection
from typing import Protocol
from uuid import UUID


class SearchApi(Protocol):
    async def response_time(self, profile_id: UUID) -> int | None:
        """«Обычно отвечает за …» (S08, 6.3b): медиана первого ответа в минутах; меньше пяти
        диалогов с ответом за 30 дней — None."""
        ...

    async def response_times(self, profile_ids: Collection[UUID]) -> dict[UUID, int]:
        """То же пачкой — карточки откликов S23; профиля без времени ответа нет в ответе."""
        ...
