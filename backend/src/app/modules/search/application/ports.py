"""Порты модуля search (ADR-0020 §3, §5): read-model специалистов, очередь её обновления,
выдача по ней и избранное."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

from app.modules.search.application.dto import (
    SpecialistFilters,
    SpecialistHit,
    TextMatch,
    ZeroResult,
    ZeroResultStat,
)
from app.modules.search.domain.favorites import FavoriteType
from app.modules.search.domain.index import IndexEntry
from app.modules.search.domain.query import RankWeights, SpecialistSort
from app.platform.contracts.events.catalog import CatalogChanged
from app.platform.contracts.events.identity import (
    UserDeleted,
    UserRestricted,
    UserRestrictionsLifted,
)
from app.platform.contracts.events.media import MediaReady
from app.platform.contracts.events.pricing import PriceListChanged
from app.platform.contracts.events.specialists import (
    AvailabilityChanged,
    ProfileDeleted,
    ProfileHidden,
    ProfilePublished,
    ProfileUpdated,
)
from app.platform.kernel.ids import CategoryId, CityId, UserId
from app.platform.queue.port import TaskRef


@dataclass(frozen=True, slots=True, kw_only=True)
class Pending:
    """Профиль, чью строку пора пересобрать. `occurred_at` — самое раннее событие, которое её
    изменило (для метрики лага); None — плановая пересборка (сверка, CLI, конец санкции)."""

    profile_id: UUID
    occurred_at: datetime | None


class SpecialistIndex(Protocol):
    """Проектор read-model (ADR-0020 §5): идемпотентный upsert строк и их удаление."""

    async def upsert(self, entries: Sequence[IndexEntry]) -> None: ...

    async def delete(self, profile_ids: Collection[UUID]) -> None: ...

    async def set_response_times(self, minutes: Mapping[UserId, int]) -> None:
        """«Обычно отвечает за …» (6.3b): медиана в минутах по пользователю; у кого её больше
        нет — NULL. Нужен активный UoW."""
        ...

    async def response_time(self, profile_id: UUID) -> int | None:
        """Медиана первого ответа специалиста в минутах; нет строки или мало диалогов — None."""
        ...

    async def ids_of_users(self, user_ids: Collection[UserId]) -> list[UUID]:
        """Строки пользователей (профиль удалён — строка ещё может быть)."""
        ...

    async def ids_with_categories(self, category_ids: Collection[CategoryId]) -> list[UUID]:
        """Строки, в чьих категориях (с предками) есть хотя бы одна из этих."""
        ...

    async def ids_after(self, after: UUID | None, *, limit: int) -> list[UUID]:
        """Все строки по id — сверка ищет строки без опубликованного профиля."""
        ...


class PendingProfiles(Protocol):
    """Очередь пересборки: событие отмечает профиль, задача пересобирает пачку (4.1)."""

    async def mark(self, profile_ids: Collection[UUID], *, occurred_at: datetime | None) -> int:
        """Отметить профили; уже отмеченный хранит самое раннее событие. Сколько отмечено."""
        ...

    async def take(self, *, limit: int) -> list[Pending]:
        """Самые давние отметки под блокировкой (SKIP LOCKED): параллельные задачи берут
        разные. Нужен активный UoW: снимаются отметки в той же транзакции."""
        ...

    async def clear(self, profile_ids: Collection[UUID]) -> None: ...

    async def count(self) -> int: ...


class SpecialistSearch(Protocol):
    """Выдача по read-model (§9.2–9.5). Порт — граница замены: при росте за ним встанет
    поисковый движок, а use case и HTTP не изменятся (ARCHITECTURE §18)."""

    async def search(
        self,
        filters: SpecialistFilters,
        match: TextMatch | None,
        *,
        sort: SpecialistSort,
        weights: RankWeights,
        offset: int,
        limit: int,
        now: datetime,
    ) -> list[SpecialistHit]:
        """До `limit` строк по порядку `sort`, начиная с `offset`."""
        ...

    async def count(
        self,
        filters: SpecialistFilters,
        match: TextMatch | None,
        *,
        now: datetime,
        cap: int,
    ) -> int:
        """Сколько строк подходит, но не больше `cap`: «Показать 1000+» дальше не считает."""
        ...

    async def count_by_category(self, city_id: CityId, kind: str) -> dict[CategoryId, int]:
        """Видимые специалисты города по категориям — с подкатегориями (дерево S04)."""
        ...

    async def listed(self, profile_ids: Collection[UUID]) -> list[SpecialistHit]:
        """Строки этих профилей, которые видны в каталоге (избранное S12), в любом порядке."""
        ...


class Favorites(Protocol):
    """Избранное пользователя (4.6). Запись — идемпотентна; нужен активный UoW."""

    async def add(self, user_id: UserId, target_type: FavoriteType, target_id: UUID) -> bool:
        """Добавить; False — уже было."""
        ...

    async def remove(self, user_id: UserId, target_type: FavoriteType, target_id: UUID) -> None: ...

    async def count(self, user_id: UserId, target_type: FavoriteType) -> int: ...

    async def ids(self, user_id: UserId, target_type: FavoriteType) -> list[UUID]:
        """Цели этого типа, новые первыми."""
        ...

    async def forget(self, user_id: UserId) -> None:
        """Всё избранное пользователя — аккаунт удалён (§7.10)."""
        ...


class QueryLog(Protocol):
    async def record(self, entry: ZeroResult) -> None:
        """Запрос без результатов (§9.2). Нужен активный UoW."""
        ...

    async def zero_results(self, since: datetime, *, limit: int) -> list[ZeroResultStat]:
        """Запросы без результатов с `since`, сгруппированные по нормализованному тексту: самые
        частые первыми."""
        ...


class IndexMetrics(Protocol):
    def observe_lag(self, seconds: float) -> None:
        """Сколько прошло от события до новой строки read-model."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class FlushPayload:
    """Задача `search.flush_index`: пересобрать отмеченные профили пачками."""

    reason: str = "events"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReindexPayload:
    """Задача `search.reindex_profiles`: отметить профили позже — в конце санкции."""

    profile_ids: tuple[UUID, ...] = field(default_factory=tuple)


FLUSH_INDEX: Final = TaskRef("search.flush_index", FlushPayload)
"""Одна ждущая задача на всех: отметки копятся, пачка пересобирается за раз (dedup).
Приоритета нет: в очереди FIFO задача ждёт только то, что стояло до неё. С приоритетом
пересборка шла на каждое событие, и лаг на бенчмарке 4.1 вырос (p95 6,1 с против 4,7 с)."""
REINDEX_PROFILES: Final = TaskRef("search.reindex_profiles", ReindexPayload)

ON_PROFILE_PUBLISHED: Final = TaskRef("search.on_profile_published", ProfilePublished)
ON_PROFILE_UPDATED: Final = TaskRef("search.on_profile_updated", ProfileUpdated)
ON_PROFILE_HIDDEN: Final = TaskRef("search.on_profile_hidden", ProfileHidden)
ON_PROFILE_DELETED: Final = TaskRef("search.on_profile_deleted", ProfileDeleted)
ON_AVAILABILITY: Final = TaskRef("search.on_availability_changed", AvailabilityChanged)
ON_PRICE_LIST: Final = TaskRef("search.on_price_list_changed", PriceListChanged)
ON_CATALOG: Final = TaskRef("search.on_catalog_changed", CatalogChanged)
ON_USER_RESTRICTED: Final = TaskRef("search.on_user_restricted", UserRestricted)
ON_USER_LIFTED: Final = TaskRef("search.on_user_restrictions_lifted", UserRestrictionsLifted)
ON_USER_DELETED: Final = TaskRef("search.on_user_deleted", UserDeleted)
ON_MEDIA_READY: Final = TaskRef("search.on_media_ready", MediaReady)
"""Подписчики событий-источников: каждое отмечает профили к пересборке (MarkProfiles)."""

FORGET_FAVORITES: Final = TaskRef("search.forget_favorites", UserDeleted)
"""Аккаунт удалён — его избранное тоже (§7.10)."""
