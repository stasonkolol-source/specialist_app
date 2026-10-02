"""Порты модуля pricing (ADR-0020 §3, §5)."""

from collections.abc import Collection
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

from app.modules.pricing.domain.service import Service, ServiceId
from app.modules.specialists.api import PriceSummary
from app.platform.contracts.events.specialists import ProfileDeleted
from app.platform.queue.port import TaskRef

REMOVE_PROFILE_PRICES: Final = TaskRef("pricing.remove_profile_prices", ProfileDeleted)
"""Подписчик ProfileDeleted: прайс удалённого аккаунта (§7.10)."""


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

    async def summary(self, profile_id: UUID) -> PriceSummary:
        """Видимые позиции профиля и сколько из них без описания."""
        ...

    async def visible(self, profile_ids: Collection[UUID]) -> list[Service]:
        """Видимые позиции профилей без блокировки — для поиска (4.1)."""
        ...
