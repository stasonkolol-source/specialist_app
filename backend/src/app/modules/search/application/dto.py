"""DTO выдачи специалистов (DEVELOPMENT_PLAN 4.2): фильтры §9.5, строки выдачи, карточки."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.search.domain.query import Stage
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId
from app.platform.kernel.pagination import Page

PRO = "pro"


@dataclass(frozen=True, slots=True, kw_only=True)
class SpecialistFilters:
    """Фильтры шторки S06 и параметры точки клиента. Город обязателен: выдача — по городу."""

    city_id: CityId
    kind: str = PRO
    """«Подработка» — только по явному фильтру (PRODUCT §2)."""
    category_id: CategoryId | None = None
    """Выбранная категория: с подкатегориями, в ней же — цена «до» и сортировка по цене."""
    district_ids: tuple[DistrictId, ...] = ()
    point: GeoPoint | None = None
    """Точка клиента: радиус, «выезжает ко мне», расстояние в карточке, сортировка рядом."""
    radius_m: int | None = None
    travels_to_me: bool = False
    price_max: int | None = None
    """Пара."""
    rating_min: float | None = None
    languages: tuple[str, ...] = ()
    work_modes: tuple[str, ...] = ()
    available_today: bool = False
    verified: bool = False
    with_reviews: bool = False

    @property
    def narrowed(self) -> bool:
        """Выбрано что-то сверх города и категории: пустой выдаче подскажем ослабить фильтры."""
        return bool(
            self.district_ids
            or self.radius_m
            or self.travels_to_me
            or self.price_max is not None
            or self.rating_min is not None
            or self.languages
            or self.work_modes
            or self.available_today
            or self.verified
            or self.with_reviews
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TextMatch:
    """Чем этап сужает выдачу: категориями словаря или текстом FTS."""

    stage: Stage
    category_ids: tuple[CategoryId, ...] = ()
    """Узнанные категории (этапы словаря): строка подходит, если в ней есть любая."""
    fts: str = ""
    """Текст для tsquery (этапы FTS)."""
    name: str = ""
    """Запрос как набран — для поиска по имени (триграммы name_norm)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SpecialistHit:
    """Строка выдачи из read-model."""

    profile_id: UUID
    card: Mapping[str, Any]
    price_from: int | None
    """Цена «от»: в выбранной категории, если там есть цена; иначе по всему прайсу."""
    rating_bayes: float | None
    rating_count: int
    badges: tuple[str, ...]
    available_until: datetime | None
    distance_m: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Avatar:
    url: str
    width: int
    height: int
    placeholder: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SpecialistCard:
    """Карточка S05: что видит клиент в выдаче."""

    profile_id: UUID
    display_name: str
    headline: str | None
    kind: str
    avatar: Avatar | None
    district_id: DistrictId | None
    district_name: Mapping[str, str]
    """Название района по языкам; язык ответа выбирает HTTP."""
    distance_m: int | None
    languages: tuple[str, ...]
    category_ids: tuple[CategoryId, ...]
    price_from: int | None
    negotiable: bool
    rating: float | None
    """Байесовское среднее — только когда отзывов достаточно; иначе «Новый специалист»."""
    rating_count: int
    is_new: bool
    available_until: datetime | None
    """Доступен сегодня до … (только если ещё доступен)."""
    badges: tuple[str, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class SpecialistResults:
    page: Page[SpecialistCard]
    stage: Stage
    category_ids: tuple[CategoryId, ...] = ()
    """Категории, в которых узнан запрос: чип «Электрик» над выдачей."""
    did_you_mean: str | None = None
    hints: tuple[str, ...] = ()
    """Пустая выдача: `relax_filters`, `post_job` — тексты на клиенте."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ZeroResult:
    """Запрос без результатов — в search.query_log для пополнения словаря (§9.2)."""

    q: str
    locale: str
    city_id: CityId
    category_id: CategoryId | None
    filters: tuple[str, ...]
    """Имена выбранных фильтров (без значений): «ослабить фильтры» или пробел в словаре."""
    did_you_mean: str | None
