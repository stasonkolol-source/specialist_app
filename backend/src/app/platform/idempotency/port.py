"""Порт IdempotencyStore: ключ пользователя, хэш запроса и сохранённый ответ (24 ч)."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class ReservationStatus(StrEnum):
    RESERVED = "reserved"
    """Ключ новый: запрос выполняется впервые."""
    COMPLETED = "completed"
    """Ответ уже есть: отдать его повторно."""
    IN_PROGRESS = "in_progress"
    """Первый запрос ещё выполняется (или процесс упал посреди него)."""
    MISMATCH = "mismatch"
    """Тот же ключ, другое тело запроса."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Reservation:
    status: ReservationStatus
    status_code: int | None = None
    response: object | None = None


class IdempotencyStore(Protocol):
    async def reserve(
        self, user_id: UUID, key: str, request_hash: bytes, *, not_before: datetime
    ) -> Reservation:
        """Занять ключ; записи старше not_before считаются истёкшими и перезанимаются."""
        ...

    async def complete(
        self, user_id: UUID, key: str, status_code: int, response: object
    ) -> None: ...

    async def release(self, user_id: UUID, key: str) -> None:
        """Освободить ключ после ошибки: повтор выполнится заново."""
        ...

    async def cleanup(self, *, before: datetime) -> int: ...
