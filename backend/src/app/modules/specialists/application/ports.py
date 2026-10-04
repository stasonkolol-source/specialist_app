"""Порты модуля specialists (ADR-0020 §3, §5)."""

from collections.abc import Collection
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

from app.modules.specialists.api import ProfileForIndex, ProfileRef, PublicCard, PublicProfile
from app.modules.specialists.application.dto import ProfileView
from app.modules.specialists.domain.portfolio import PortfolioItem
from app.modules.specialists.domain.profile import Profile, ProfileId
from app.platform.contracts.events.identity import UserDeleted
from app.platform.kernel.ids import MediaId, UserId
from app.platform.queue.port import TaskRef

FORGET_PROFILE: Final = TaskRef("specialists.forget_profile", UserDeleted)
"""Подписчик UserDeleted: профиль и портфолио удалённого аккаунта (§7.10)."""


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

    async def stale(
        self, *, updated_before: datetime, reminded_before: datetime, now: datetime, limit: int
    ) -> list[tuple[ProfileId, UserId]]:
        """Опубликованные профили, не менявшиеся с `updated_before` (правка, «доступен
        сегодня» — любое изменение строки), сейчас не «доступные» и не в отпуске, которым не
        напоминали после `reminded_before`, — пропуская занятые (SKIP LOCKED)."""
        ...

    async def mark_reminded(self, profile_ids: Collection[ProfileId], at: datetime) -> None:
        """Отметить напоминание, не меняя `updated_at` и версию: отметка — не правка профиля."""
        ...


class ProfileQuery(Protocol):
    async def of_user(self, user_id: UserId) -> ProfileView | None:
        """Свой профиль для кабинета (GET /me/profile)."""
        ...

    async def refs_of_users(self, user_ids: Collection[UserId]) -> dict[UserId, ProfileRef]:
        """Профили пользователей пачкой (без удалённых): id, вид и статус."""
        ...

    async def for_index(self, profile_ids: Collection[UUID]) -> list[ProfileForIndex]:
        """Неудалённые профили для поиска — пачкой."""
        ...

    async def public(self, profile_id: UUID) -> PublicProfile | None:
        """Опубликованный профиль с опубликованными работами (S08)."""
        ...

    async def public_cards(self, profile_ids: Collection[UUID]) -> dict[UUID, PublicCard]:
        """Опубликованные профили карточками — одним запросом на пачку."""
        ...

    async def published_ids(self, *, after: UUID | None, limit: int) -> list[UUID]:
        """Опубликованные профили по id после `after`."""
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

    async def by_media(self, media_ids: Collection[MediaId]) -> list[PortfolioItem]:
        """Неудалённые работы с этими файлами — для модерации (дубликаты фото, 7.6)."""
        ...
