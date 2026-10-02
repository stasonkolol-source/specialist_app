"""Подсчёты для экранов каталога (DEVELOPMENT_PLAN 4.4): «Показать N» и числа в дереве S04."""

from datetime import timedelta

import pytest

from app.modules.catalog.api import TermMatch
from app.modules.search.application.dto import SpecialistFilters
from app.modules.search.application.use_cases.count_by_category import (
    CountByCategory,
    CountByCategoryCommand,
)
from app.modules.search.application.use_cases.count_specialists import (
    COUNT_CAP,
    CountSpecialists,
    CountSpecialistsCommand,
)
from app.modules.search.domain.query import Stage
from app.modules.search.tests.fakes import FakeCache, FakeCatalog, FakeSearch
from app.modules.search.tests.unit.test_search_specialists import CITY, hit
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.ids import CategoryId
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.unit

FILTERS = SpecialistFilters(city_id=CITY)


def counter() -> tuple[FakeSearch, FakeCatalog, CountSpecialists]:
    search, catalog = FakeSearch(), FakeCatalog()
    return search, catalog, CountSpecialists(search, catalog, FakeClock())


async def test_count_is_the_first_stage_that_finds_someone() -> None:
    search, _, count = counter()
    search.by_stage[Stage.PREFIX] = [hit(1), hit(2)]

    found = await count(CountSpecialistsCommand(filters=FILTERS, q="ремонт ванной"))

    assert (found.count, found.capped) == (2, False)
    assert search.counted == [Stage.ALL_WORDS, Stage.PREFIX]


async def test_count_follows_a_recognized_category() -> None:
    search, catalog, count = counter()
    catalog.matches["электрик"] = TermMatch(category_ids=(CategoryId(5),), term="x", exact=True)
    search.by_stage[Stage.TAXONOMY] = [hit(1)]

    found = await count(CountSpecialistsCommand(filters=FILTERS, q="электрик"))

    assert found.count == 1
    assert search.counted == [Stage.TAXONOMY]


async def test_count_stops_at_the_cap() -> None:
    search, _, count = counter()
    search.by_stage[Stage.BROWSE] = [hit(number) for number in range(COUNT_CAP + 5)]

    found = await count(CountSpecialistsCommand(filters=FILTERS))

    assert (found.count, found.capped) == (COUNT_CAP, True)


async def test_nothing_found_counts_zero() -> None:
    _, _, count = counter()

    found = await count(CountSpecialistsCommand(filters=FILTERS, q="qwerty"))

    assert (found.count, found.capped) == (0, False)


async def test_radius_without_a_point_is_rejected() -> None:
    _, _, count = counter()

    with pytest.raises(DomainValidationError):
        await count(
            CountSpecialistsCommand(filters=SpecialistFilters(city_id=CITY, radius_m=3_000))
        )


async def test_category_counts_are_cached_per_city_and_kind() -> None:
    search, cache = FakeSearch(), FakeCache()
    search.categories = {CategoryId(1): 7, CategoryId(5): 3}
    counts = CountByCategory(search, cache)

    first = await counts(CountByCategoryCommand(city_id=CITY))
    again = await counts(CountByCategoryCommand(city_id=CITY))

    assert first == again == {CategoryId(1): 7, CategoryId(5): 3}
    assert search.counted_categories == [(CITY, "pro")]
    assert cache.ttls == {f"search.category_counts:v1:pro:{CITY}": timedelta(minutes=5)}
