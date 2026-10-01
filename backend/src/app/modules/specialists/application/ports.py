"""Порты модуля specialists (ADR-0020 §3, §5)."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.specialists.application.dto import ProfileView
from app.modules.specialists.domain.portfolio import PortfolioItem
from app.modules.specialists.domain.profile import Profile, ProfileId
from app.platform.kernel.ids import UserId


class ProfileRepository(Protocol):
    async def of_user(self, user_id: UserId) -> Profile | None:
        """Профиль пользователя под блокировкой строки; удалённого нет."""
        ...

    async def get_for_update(self, profile_id: ProfileId) -> Profile:
        """ProfileNotFoundError — нет такого или удалён."""
        ...

    async def add(self, profile: Profile) -> None:
        """ProfileExistsError — у пользователя уже есть профиль."""
        ...

    async def save(self, profile: Profile) -> None: ...

    async def expired_availability(self, now: datetime, *, limit: int) -> list[ProfileId]:
        """Профили с истёкшим «доступен сегодня» — пропуская занятые другими (SKIP LOCKED)."""
        ...


class ProfileQuery(Protocol):
    async def of_user(self, user_id: UserId) -> ProfileView | None:
        """Свой профиль для кабинета (GET /me/profile)."""
        ...


class PortfolioRepository(Protocol):
    async def list_for_update(self, profile_id: UUID) -> list[PortfolioItem]:
        """Все работы профиля под блокировкой строк — по позиции."""
        ...

    async def add(self, item: PortfolioItem) -> None: ...

    async def save(self, item: PortfolioItem) -> None: ...


class PortfolioQuery(Protocol):
    async def of_profile(self, profile_id: UUID) -> list[PortfolioItem]:
        """Работы профиля по порядку, без блокировки: S37 и полнота профиля."""
        ...
