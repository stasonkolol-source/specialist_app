"""Подсказки при вводе (DEVELOPMENT_PLAN 4.3a): кэш на 5 минут по вводу в своём алфавите."""

from datetime import timedelta

import pytest

from app.modules.catalog.api import CategorySuggestion
from app.modules.search.application.use_cases.suggest_categories import (
    SuggestCategories,
    SuggestCategoriesCommand,
)
from app.modules.search.tests.fakes import FakeCache, FakeCatalog
from app.platform.kernel.ids import CategoryId
from app.platform.kernel.localized import Locale, LocalizedText

pytestmark = pytest.mark.unit

ELECTRICIAN = CategorySuggestion(
    category_id=CategoryId(5),
    name=LocalizedText({Locale.RU: "Электрик", Locale.SR_CYRL: "Електричар"}),
    icon="bolt",
    term="Električar",
    fuzzy=False,
)


def world() -> tuple[FakeCatalog, FakeCache, SuggestCategories]:
    catalog, cache = FakeCatalog(), FakeCache()
    return catalog, cache, SuggestCategories(catalog, cache)


async def test_first_input_asks_the_dictionary_and_caches_five_minutes() -> None:
    catalog, cache, suggest = world()
    catalog.suggestions["Elek"] = [ELECTRICIAN]

    found = await suggest(SuggestCategoriesCommand(q="  Elek "))

    assert found == [ELECTRICIAN]
    assert catalog.suggested == [("Elek", 8)]
    assert cache.ttls == {"search.suggest:v1:elek": timedelta(minutes=5)}


async def test_same_input_comes_from_the_cache() -> None:
    catalog, _, suggest = world()
    catalog.suggestions["elek"] = [ELECTRICIAN]

    first = await suggest(SuggestCategoriesCommand(q="elek"))
    again = await suggest(SuggestCategoriesCommand(q="ELEK"))

    assert first == again == [ELECTRICIAN]
    assert catalog.suggested == [("elek", 8)]


async def test_other_script_is_another_key() -> None:
    _, cache, suggest = world()

    await suggest(SuggestCategoriesCommand(q="elek"))
    await suggest(SuggestCategoriesCommand(q="елек"))

    assert sorted(cache.values) == ["search.suggest:v1:elek", "search.suggest:v1:елек"]


async def test_too_short_input_asks_nothing() -> None:
    catalog, cache, suggest = world()

    assert await suggest(SuggestCategoriesCommand(q=" e ")) == []
    assert (catalog.suggested, cache.values) == ([], {})


async def test_broken_cache_entry_is_asked_again() -> None:
    catalog, cache, suggest = world()
    catalog.suggestions["elek"] = [ELECTRICIAN]
    cache.values["search.suggest:v1:elek"] = '[{"category_id": "x"}]'

    assert await suggest(SuggestCategoriesCommand(q="elek")) == [ELECTRICIAN]
    assert catalog.suggested == [("elek", 8)]


async def test_control_characters_never_reach_the_dictionary() -> None:
    catalog, cache, suggest = world()

    await suggest(SuggestCategoriesCommand(q="el\x00ek"))

    assert catalog.suggested == [("el ek", 8)]
    assert list(cache.values) == ["search.suggest:v1:el ek"]
