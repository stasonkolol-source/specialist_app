"""Рейтинг профиля (ADR-0016; ARCHITECTURE §7.9): байесовское среднее для показа, нижняя граница
для ранжирования, затухание с half-life 12 месяцев, среднее категории как априорное."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.reviews.api import NO_REVIEWS_LOWER_BOUND as API_NO_REVIEWS_LOWER_BOUND
from app.modules.reviews.domain.rating import (
    NO_REVIEWS_LOWER_BOUND,
    PRIOR_MEAN,
    CategoryStats,
    Rated,
    category_mean,
    lower_bound,
    rate,
    weight,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 3, tzinfo=UTC)


def rated(rating: int, *, ago: timedelta = timedelta(0), category: int | None = None) -> Rated:
    return Rated(rating=rating, criteria={}, published_at=NOW - ago, category_id=category)


def test_examples_from_the_adr() -> None:
    """m = 4,6: одна «пятёрка» → 4,67; 40 отзывов со средним 4,8 → 4,78."""
    one = rate([rated(5)], categories={}, now=NOW)
    many = rate([rated(5)] * 32 + [rated(4)] * 8, categories={}, now=NOW)

    assert one is not None
    assert many is not None
    assert round(one.bayes, 2) == 4.67
    assert round(many.bayes, 2) == 4.78
    assert many.average == pytest.approx(4.8)
    assert many.distribution == (0, 0, 0, 8, 32)
    assert one.lower_bound < many.lower_bound  # новичок не обгоняет опытного


def test_lower_bound_ranks_no_reviews_between_one_bad_and_one_good() -> None:
    bad = rate([rated(1)], categories={}, now=NOW)
    good = rate([rated(5)], categories={}, now=NOW)

    assert bad is not None
    assert good is not None
    assert bad.lower_bound < NO_REVIEWS_LOWER_BOUND < good.lower_bound
    assert lower_bound([0.0] * 5) == NO_REVIEWS_LOWER_BOUND
    assert round(NO_REVIEWS_LOWER_BOUND, 2) == API_NO_REVIEWS_LOWER_BOUND


def test_old_reviews_weigh_less() -> None:
    assert weight(NOW, NOW) == 1.0
    assert weight(NOW - timedelta(days=365), NOW) == pytest.approx(0.5)
    assert weight(NOW + timedelta(hours=1), NOW) == 1.0  # часы чуть разошлись — не больше 1

    fresh_bad = rate([rated(5, ago=timedelta(days=730)), rated(1)], categories={}, now=NOW)
    old_bad = rate([rated(5), rated(1, ago=timedelta(days=730))], categories={}, now=NOW)
    assert fresh_bad is not None
    assert old_bad is not None
    assert fresh_bad.bayes < old_bad.bayes
    assert fresh_bad.count == old_bad.count == 2  # число и среднее — без весов
    assert fresh_bad.average == old_bad.average == 3.0


def test_category_mean_is_pulled_to_the_prior_until_it_has_reviews() -> None:
    assert category_mean(None) == PRIOR_MEAN
    assert category_mean(CategoryStats(count=1, total=1)) == pytest.approx((20 * 4.6 + 1) / 21)
    assert category_mean(CategoryStats(count=2000, total=8000)) == pytest.approx(4.0, abs=0.01)

    harsh: dict[int | None, CategoryStats] = {3: CategoryStats(count=2000, total=8000)}
    same_reviews = [rated(5, category=3)]
    in_harsh = rate(same_reviews, categories=harsh, now=NOW)
    in_unknown = rate([rated(5, category=9)], categories=harsh, now=NOW)
    assert in_harsh is not None
    assert in_unknown is not None
    assert in_harsh.bayes < in_unknown.bayes


def test_criteria_average_only_where_rated() -> None:
    result = rate(
        [
            Rated(rating=5, criteria={"quality": 5}, published_at=NOW, category_id=None),
            Rated(
                rating=4, criteria={"quality": 4, "price": 3}, published_at=NOW, category_id=None
            ),
            Rated(rating=4, criteria={}, published_at=NOW - timedelta(days=1), category_id=None),
        ],
        categories={},
        now=NOW,
    )

    assert result is not None
    assert result.criteria == {"price": 3.0, "quality": 4.5}
    assert result.last_published_at == NOW


def test_no_reviews_no_rating() -> None:
    assert rate([], categories={}, now=NOW) is None
