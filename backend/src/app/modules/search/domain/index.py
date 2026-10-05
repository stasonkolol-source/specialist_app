"""Строка read-model поиска специалиста (ARCHITECTURE §7.3, §9.3–9.5; DEVELOPMENT_PLAN 4.1).

Одна денормализованная строка на опубликованный профиль: выдача фильтрует и сортирует её без
JOIN по модулям. Здесь — чистые правила: какие категории попадают в фильтр (с предками),
цена «от» по категориям, тексты документа поиска по весам A–D и базовый балл. Векторы
`tsvector` строит PostgreSQL из этих текстов (infrastructure).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, UserId

FRESH_FOR: Final = timedelta(days=30)
"""Профиль, который правили за этот срок, считается свежим полностью."""
STALE_AFTER: Final = timedelta(days=180)
"""Дальше свежесть — ноль; между — линейно."""
ABOUT_ENOUGH: Final = 80
"""«О себе» хотя бы в пару предложений — как в полноте профиля (specialists)."""

WEIGHT_RATING: Final = 0.25
WEIGHT_TRUST: Final = 0.15
WEIGHT_ACTIVITY: Final = 0.05
"""Веса базового балла — доли формулы ранжирования §9.4 без текста, отзывчивости и
расстояния (их добавит выдача 4.2). До бейджей балл решают рейтинг и активность."""
RATING_SCALE: Final = 5.0
"""Нижняя граница рейтинга — по шкале 1–5; в балл — доля от 0 до 1."""


_DJ: Final = str.maketrans({"đ": "dj", "Đ": "Dj", "ђ": "dj", "Ђ": "Dj"})


def serbian(text: str) -> str:
    """Сербский текст для FTS — и документ, и запрос (§9.3): `đ` → `dj`, иначе unaccent
    сделает из него `d`, и «gradjevina» не найдёт «građevina». Кириллическая `ђ` — так же:
    транслитерация platform.sr_cyr2lat дала бы из неё ту же `đ`."""
    return text.translate(_DJ)


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchDocument:
    """Тексты документа поиска по весам (§9.3). Язык «о себе» и прайса неизвестен: они идут
    и в русскую, и в сербскую конфигурацию."""

    names_ru: str = ""
    names_sr: str = ""
    names_en: str = ""
    """A: имя и названия категорий профиля."""
    terms_ru: str = ""
    terms_sr: str = ""
    terms_en: str = ""
    """B: словарь поиска категорий — синонимы, теги."""
    prices: str = ""
    """C: названия позиций прайса."""
    about: str = ""
    """D: «коротко о себе» и «о себе»."""


@dataclass(frozen=True, slots=True, kw_only=True)
class IndexEntry:
    profile_id: UUID
    user_id: UserId
    kind: str
    is_listed: bool
    """Виден в каталоге по умолчанию: «Подработка» — только по явному фильтру (PRODUCT §2)."""
    city_id: CityId
    district_id: DistrictId | None
    district_ids: tuple[DistrictId, ...]
    base_point: GeoPoint | None
    base_point_public: GeoPoint | None
    travel_radius_m: int | None
    category_ids: tuple[CategoryId, ...]
    """Категории профиля и все их предки: фильтр «с подкатегориями» без рекурсии."""
    languages: tuple[str, ...]
    work_modes: tuple[str, ...]
    price_from: int | None
    category_prices: Mapping[CategoryId, int]
    available_until: datetime | None
    activity_score: float
    rating_bayes: float | None
    """Фильтр «рейтинг от» и сортировка «по рейтингу»; без отзывов по сделкам — None. Показ —
    простое среднее в карточке (`card["rating"]`, UXM-17)."""
    rating_lower_bound: float | None
    """Ранжирование; без отзывов — None (выдача берёт априорную границу)."""
    rating_count: int
    score: float
    name: str
    document: SearchDocument
    card: Mapping[str, Any]
    source_updated_at: datetime


def with_ancestors(paths: Iterable[Sequence[CategoryId]]) -> tuple[CategoryId, ...]:
    """Категории и их предки без повторов, по возрастанию id."""
    return tuple(sorted({category for path in paths for category in path}))


def category_prices(
    lowest: Mapping[CategoryId, int], paths: Mapping[CategoryId, Sequence[CategoryId]]
) -> dict[CategoryId, int]:
    """Цена «от» в каждой категории и её предках: «до N в электрике» видит и «Мастер на час»."""
    return {category: lowest[source] for category, source in _cheapest(lowest, paths).items()}


def category_price_units(
    lowest: Mapping[CategoryId, int],
    units: Mapping[CategoryId, str | None],
    paths: Mapping[CategoryId, Sequence[CategoryId]],
) -> dict[CategoryId, str | None]:
    """Единица цены `category_prices` в каждой категории и её предках — той группы, что дала цену:
    в выдаче по «Мелкому ремонту» «от 2 000 RSD/час», а не единица самой дешёвой позиции прайса."""
    return {category: units.get(source) for category, source in _cheapest(lowest, paths).items()}


def _cheapest(
    lowest: Mapping[CategoryId, int], paths: Mapping[CategoryId, Sequence[CategoryId]]
) -> dict[CategoryId, CategoryId]:
    """Категория и каждый её предок → группа прайса с самой низкой ценой; при равных — первая."""
    found: dict[CategoryId, CategoryId] = {}
    for category_id, price in lowest.items():
        for ancestor in paths.get(category_id, (category_id,)):
            known = found.get(ancestor)
            if known is None or price < lowest[known]:
                found[ancestor] = category_id
    return found


def freshness(updated_at: datetime, now: datetime) -> float:
    """1 — правили недавно, 0 — полгода и дольше назад."""
    age = now - updated_at
    if age <= FRESH_FOR:
        return 1.0
    if age >= STALE_AFTER:
        return 0.0
    return 1.0 - (age - FRESH_FOR) / (STALE_AFTER - FRESH_FOR)


def activity_score(
    *, has_avatar: bool, about: str | None, has_prices: bool, updated_at: datetime, now: datetime
) -> float:
    """Активность 0–1 (§9.4): полнота, что видит клиент, и свежесть. Отзывчивость — 6.3b."""
    parts = (
        1.0 if has_avatar else 0.0,
        1.0 if len((about or "").strip()) >= ABOUT_ENOUGH else 0.0,
        1.0 if has_prices else 0.0,
        freshness(updated_at, now),
    )
    return sum(parts) / len(parts)


def base_score(*, rating_lower_bound: float, trust: float, activity: float) -> float:
    """Базовый балл 0–1 для сортировки без текста запроса (keyset в выдаче). Нижняя граница
    рейтинга — по шкале 1–5 (у профиля без отзывов — априорная, reviews 7.2)."""
    total = WEIGHT_RATING + WEIGHT_TRUST + WEIGHT_ACTIVITY
    rating = rating_lower_bound / RATING_SCALE
    raw = WEIGHT_RATING * rating + WEIGHT_TRUST * trust + WEIGHT_ACTIVITY * activity
    return raw / total


@dataclass(frozen=True, slots=True)
class Labels:
    """Названия и словарь категорий по языкам интерфейса (ru, sr-Latn, sr-Cyrl, en)."""

    by_lang: dict[str, list[str]] = field(default_factory=dict)

    def add(self, lang: str, text: str) -> None:
        if text:
            self.by_lang.setdefault(lang, []).append(text)

    def joined(self, *langs: str) -> str:
        return " ; ".join(text for lang in langs for text in self.by_lang.get(lang, ()))
