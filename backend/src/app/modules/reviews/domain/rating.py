"""Рейтинг профиля по опубликованным отзывам сделок (ADR-0016; ARCHITECTURE §7.9, §9.4).

- **Показ и фильтр «рейтинг от»** — байесовское среднее `(C·m + Σ wᵢ·rᵢ) / (C + Σ wᵢ)`, `C = 5`,
  `m` — среднее по категориям отзывов профиля. Пока отзывов в категории мало, её среднее
  притянуто к `PRIOR_MEAN` (на площадках услуг оценки завышены: около 97% положительных).
- **Ранжирование** — нижняя граница доверительного интервала среднего с Dirichlet prior (по
  единице на каждую звезду): новичок с одной «пятёркой» не обгоняет мастера с сорока отзывами.
- **Затухание** — вес отзыва `wᵢ` вдвое меньше каждые 12 месяцев (half-life).

Число отзывов, гистограмма и средние по критериям — без весов: это то, что человек видит.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

C: Final = 5.0
"""Вес априорного среднего в отзывах (§7.9)."""
PRIOR_MEAN: Final = 4.6
"""Среднее «по рынку», пока своих отзывов мало (пример ADR-0016)."""
CATEGORY_PRIOR_WEIGHT: Final = 20.0
"""Столько отзывов нужно категории, чтобы её среднее весило наравне с `PRIOR_MEAN`."""
HALF_LIFE: Final = timedelta(days=365)
Z: Final = 1.645
"""Односторонние 95%: нижняя граница для ранжирования."""
STARS: Final = 5


@dataclass(frozen=True, slots=True, kw_only=True)
class Rated:
    """Опубликованный отзыв для расчёта."""

    rating: int
    criteria: Mapping[str, int]
    published_at: datetime
    category_id: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class CategoryStats:
    """Опубликованные отзывы категории: сколько и сумма оценок."""

    count: int
    total: int


@dataclass(frozen=True, slots=True, kw_only=True)
class Rating:
    count: int
    average: float
    """Простое среднее."""
    bayes: float
    """Показ («4,9») и фильтр «рейтинг от»."""
    lower_bound: float
    """Ранжирование."""
    distribution: tuple[int, ...]
    """Сколько оценок в 1, 2, 3, 4 и 5 звёзд."""
    criteria: dict[str, float]
    last_published_at: datetime


def weight(published_at: datetime, now: datetime) -> float:
    """Вес отзыва: 1 — свежий, ½ — год назад, ¼ — два."""
    age = max(now - published_at, timedelta(0))
    return math.pow(0.5, age / HALF_LIFE)


def category_mean(stats: CategoryStats | None) -> float:
    """Среднее категории, притянутое к `PRIOR_MEAN`, пока отзывов в ней мало."""
    if stats is None:
        return PRIOR_MEAN
    return (CATEGORY_PRIOR_WEIGHT * PRIOR_MEAN + stats.total) / (
        CATEGORY_PRIOR_WEIGHT + stats.count
    )


def prior_mean(reviews: Iterable[Rated], categories: Mapping[int | None, CategoryStats]) -> float:
    """`m` профиля: средние категорий его отзывов (у отзыва без категории — всей площадки)."""
    means = [category_mean(categories.get(review.category_id)) for review in reviews]
    return sum(means) / len(means) if means else PRIOR_MEAN


def lower_bound(weighted_counts: Sequence[float]) -> float:
    """Нижняя граница среднего при Dirichlet prior в единицу на звезду (Evan Miller, «Ranking
    items with star ratings»): без отзывов — 3 − 1,645·√(2/6) ≈ 2,05."""
    pseudo = [count + 1.0 for count in weighted_counts]
    total = sum(pseudo)
    pairs = list(zip(range(1, STARS + 1), pseudo, strict=True))
    mean = sum(star * count for star, count in pairs) / total
    second = sum(star * star * count for star, count in pairs) / total
    return mean - Z * math.sqrt(max(second - mean * mean, 0.0) / (total + 1))


NO_REVIEWS_LOWER_BOUND: Final = lower_bound([0.0] * STARS)


def rate(
    reviews: Sequence[Rated],
    *,
    categories: Mapping[int | None, CategoryStats],
    now: datetime,
) -> Rating | None:
    """Рейтинг профиля; без опубликованных отзывов — None («Новый специалист»)."""
    if not reviews:
        return None
    weights = [weight(review.published_at, now) for review in reviews]
    weighted = [0.0] * STARS
    distribution = [0] * STARS
    for review, w in zip(reviews, weights, strict=True):
        weighted[review.rating - 1] += w
        distribution[review.rating - 1] += 1
    m = prior_mean(reviews, categories)
    bayes = (C * m + sum(w * r.rating for r, w in zip(reviews, weights, strict=True))) / (
        C + sum(weights)
    )
    return Rating(
        count=len(reviews),
        average=sum(review.rating for review in reviews) / len(reviews),
        bayes=bayes,
        lower_bound=lower_bound(weighted),
        distribution=tuple(distribution),
        criteria=_criteria(reviews),
        last_published_at=max(review.published_at for review in reviews),
    )


def _criteria(reviews: Iterable[Rated]) -> dict[str, float]:
    """Средние по критериям среди отзывов, где критерий оценён."""
    sums: dict[str, list[int]] = {}
    for review in reviews:
        for name, value in review.criteria.items():
            sums.setdefault(name, []).append(value)
    return {name: sum(values) / len(values) for name, values in sorted(sums.items())}
