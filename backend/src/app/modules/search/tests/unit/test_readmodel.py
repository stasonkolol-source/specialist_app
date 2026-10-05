"""Правила строки read-model (DEVELOPMENT_PLAN 4.1): категории с предками, цены, балл."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.search.domain.index import (
    Labels,
    activity_score,
    base_score,
    category_price_units,
    category_prices,
    freshness,
    serbian,
    with_ancestors,
)
from app.platform.kernel.ids import CategoryId

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
REPAIR, ELECTRIC, LAMPS, CLEANING = (CategoryId(i) for i in (1, 12, 120, 3))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Građevina", "Gradjevina"),
        ("ĐORĐE", "DjORDjE"),
        ("Грађевина", "Граdjевина"),
        ("Ђорђе", "Djорdjе"),
        ("električar", "električar"),
    ],
)
def test_serbian_spells_dj_out(text: str, expected: str) -> None:
    assert serbian(text) == expected


def test_categories_come_with_their_ancestors_once() -> None:
    paths = [(REPAIR, ELECTRIC, LAMPS), (REPAIR, ELECTRIC), (CLEANING,)]

    assert with_ancestors(paths) == (REPAIR, CLEANING, ELECTRIC, LAMPS)


def test_lowest_price_reaches_ancestors() -> None:
    paths = {LAMPS: (REPAIR, ELECTRIC, LAMPS), CLEANING: (CLEANING,), ELECTRIC: (REPAIR, ELECTRIC)}

    prices = category_prices({LAMPS: 300_000, ELECTRIC: 150_000, CLEANING: 90_000}, paths)

    assert prices == {REPAIR: 150_000, ELECTRIC: 150_000, LAMPS: 300_000, CLEANING: 90_000}


def test_price_of_unknown_category_stays_on_it() -> None:
    assert category_prices({LAMPS: 100}, {}) == {LAMPS: 100}


def test_unit_follows_the_lowest_price_to_ancestors() -> None:
    paths = {LAMPS: (REPAIR, ELECTRIC, LAMPS), CLEANING: (CLEANING,), ELECTRIC: (REPAIR, ELECTRIC)}
    lowest = {LAMPS: 300_000, ELECTRIC: 150_000, CLEANING: 90_000}

    units = category_price_units(lowest, {LAMPS: "item", ELECTRIC: "hour"}, paths)

    assert units == {REPAIR: "hour", ELECTRIC: "hour", LAMPS: "item", CLEANING: None}
    assert units.keys() == category_prices(lowest, paths).keys()


def test_equal_prices_keep_the_unit_of_the_first_group() -> None:
    paths = {LAMPS: (REPAIR, ELECTRIC, LAMPS), ELECTRIC: (REPAIR, ELECTRIC)}

    units = category_price_units(
        {LAMPS: 100, ELECTRIC: 100}, {LAMPS: "item", ELECTRIC: "hour"}, paths
    )

    assert units == {REPAIR: "item", ELECTRIC: "item", LAMPS: "item"}


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(0), 1.0),
        (timedelta(days=30), 1.0),
        (timedelta(days=105), 0.5),
        (timedelta(days=180), 0.0),
        (timedelta(days=400), 0.0),
    ],
)
def test_freshness_fades_linearly(age: timedelta, expected: float) -> None:
    assert freshness(NOW - age, NOW) == pytest.approx(expected)


def test_activity_counts_what_the_client_sees() -> None:
    full = activity_score(
        has_avatar=True, about="о себе " * 20, has_prices=True, updated_at=NOW, now=NOW
    )
    empty = activity_score(
        has_avatar=False,
        about="  коротко  ",
        has_prices=False,
        updated_at=NOW - timedelta(days=365),
        now=NOW,
    )
    half = activity_score(
        has_avatar=True, about=None, has_prices=True, updated_at=NOW - timedelta(days=365), now=NOW
    )

    assert (full, empty, half) == (1.0, 0.0, 0.5)


def test_base_score_mixes_rating_on_the_five_star_scale_trust_and_activity() -> None:
    assert base_score(rating_lower_bound=0.0, trust=0.0, activity=1.0) == pytest.approx(0.05 / 0.45)
    assert base_score(rating_lower_bound=5.0, trust=1.0, activity=1.0) == pytest.approx(1.0)
    assert base_score(rating_lower_bound=2.5, trust=0.0, activity=0.0) == pytest.approx(
        0.25 * 0.5 / 0.45
    )


def test_labels_join_languages_in_order() -> None:
    labels = Labels()
    labels.add("sr-Cyrl", "Електричар")
    labels.add("sr-Latn", "Električar")
    labels.add("ru", "")

    assert labels.joined("sr-Latn", "sr-Cyrl") == "Električar ; Електричар"
    assert labels.joined("ru") == ""
