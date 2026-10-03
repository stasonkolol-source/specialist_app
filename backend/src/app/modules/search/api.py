"""Контракт модуля search для других модулей: фасад (Protocol) и DTO (ADR-0020 §6).

Другие модули импортируют из search только этот файл.
"""

from typing import Protocol
from uuid import UUID


class SearchApi(Protocol):
    async def response_time(self, profile_id: UUID) -> int | None:
        """«Обычно отвечает за …» (S08, 6.3b): медиана первого ответа в минутах; меньше пяти
        диалогов с ответом за 30 дней — None."""
        ...
