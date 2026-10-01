"""Порты модуля pricing (ADR-0020 §3, §5)."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.pricing.domain.service import Service, ServiceId


class ServiceRepository(Protocol):
    async def list_for_update(self, profile_id: UUID) -> list[Service]:
        """Весь прайс профиля под блокировкой строк, по позиции."""
        ...

    async def get_for_update(self, profile_id: UUID, service_id: ServiceId) -> Service:
        """ServiceNotFoundError — нет такой позиции у профиля (чужая — тоже)."""
        ...

    async def add(self, service: Service) -> None: ...

    async def save(self, service: Service) -> None: ...

    async def delete(self, service: Service, *, now: datetime) -> None: ...

    async def has_active(self, profile_id: UUID) -> bool: ...
