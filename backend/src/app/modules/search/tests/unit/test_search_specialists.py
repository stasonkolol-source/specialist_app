"""Этапы выдачи специалистов (DEVELOPMENT_PLAN 4.2, ARCHITECTURE §9.2) на фейках."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from app.modules.catalog.api import TermMatch
from app.modules.media.api import MediaRef, MediaVariantRef
from app.modules.search.application.dto import SpecialistFilters, SpecialistHit, SpecialistResults
from app.modules.search.application.use_cases.search_specialists import (
    SearchSpecialists,
    SearchSpecialistsCommand,
)
from app.modules.search.domain.query import RankWeights, SpecialistSort, Stage
from app.modules.search.tests.fakes import (
    FakeCatalog,
    FakeFlags,
    FakeLog,
    FakeMedia,
    FakeSearch,
    FakeUoW,
)
from app.platform.kernel.errors import DomainValidationError
from app.platform.kernel.ids import CategoryId, CityId, MediaId
from app.platform.kernel.pagination import PageRequest
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
CITY = CityId(1)
ELECTRIC = CategoryId(5)
ELECTRICIAN = TermMatch(category_ids=(ELECTRIC,), term="Электрик", exact=True)


def hit(number: int, **fields: Any) -> SpecialistHit:
    card = {
        "display_name": f"Мастер {number}",
        "headline": "Электрик, 10 лет",
        "kind": "pro",
        "avatar": None,
        "district": {"id": 7, "name": {"ru": "Лиман", "sr-Cyrl": "Лиман"}},
        "languages": ["ru", "sr"],
        "category_ids": [1, 5],
        "negotiable": False,
    }
    values: dict[str, Any] = {
        "profile_id": UUID(int=number),
        "card": card,
        "price_from": 150_000,
        "rating_bayes": None,
        "rating_count": 0,
        "badges": (),
        "available_until": None,
        "distance_m": None,
    }
    return SpecialistHit(**(values | fields))


class World:
    def __init__(self) -> None:
        self.search, self.catalog, self.media = FakeSearch(), FakeCatalog(), FakeMedia()
        self.flags, self.log, self.uow = FakeFlags(), FakeLog(), FakeUoW()
        self.use_case = SearchSpecialists(
            self.search, self.catalog, self.media, self.flags, self.log, self.uow, FakeClock(NOW)
        )

    async def run(
        self,
        q: str | None = None,
        *,
        filters: SpecialistFilters | None = None,
        **command: Any,
    ) -> SpecialistResults:
        return await self.use_case(
            SearchSpecialistsCommand(
                filters=filters or SpecialistFilters(city_id=CITY), q=q, **command
            )
        )

    def stages(self) -> list[Stage]:
        return [call.stage for call in self.search.calls]


async def test_without_text_the_catalog_is_browsed() -> None:
    world = World()
    world.search.by_stage[Stage.BROWSE] = [hit(1), hit(2)]

    results = await world.run()

    assert (results.stage, len(results.page.items), results.page.next_cursor) == (
        Stage.BROWSE,
        2,
        None,
    )
    assert world.stages() == [Stage.BROWSE]


async def test_recognized_category_comes_before_text_search() -> None:
    world = World()
    world.catalog.matches["электрик"] = ELECTRICIAN
    world.search.by_stage[Stage.TAXONOMY] = [hit(1)]

    results = await world.run("электрик")

    assert (results.stage, results.category_ids, results.did_you_mean) == (
        Stage.TAXONOMY,
        (ELECTRIC,),
        None,
    )
    assert world.stages() == [Stage.TAXONOMY]


async def test_text_search_relaxes_from_all_words_to_any_word() -> None:
    world = World()
    world.search.by_stage[Stage.ANY_WORD] = [hit(1)]

    results = await world.run("ремонт ванной комнаты")

    assert results.stage is Stage.ANY_WORD
    assert world.stages() == [Stage.ALL_WORDS, Stage.PREFIX, Stage.ANY_WORD]
    any_word = world.search.calls[-1].match
    assert any_word is not None
    assert (any_word.fts, any_word.name) == (
        "ремонт or ванной or комнаты",
        "ремонт ванной комнаты",
    )


async def test_similar_word_is_the_last_resort() -> None:
    world = World()
    world.catalog.similar["elektricr"] = TermMatch(
        category_ids=(ELECTRIC,), term="Električar", exact=False
    )
    world.search.by_stage[Stage.SIMILAR] = [hit(1)]

    results = await world.run("elektricr")

    assert (results.stage, results.did_you_mean, results.category_ids) == (
        Stage.SIMILAR,
        "Električar",
        (ELECTRIC,),
    )
    assert world.stages() == [Stage.ALL_WORDS, Stage.PREFIX, Stage.ANY_WORD, Stage.SIMILAR]


async def test_empty_category_falls_back_to_text_but_not_to_a_similar_word() -> None:
    world = World()
    world.catalog.matches["уборка"] = replace(ELECTRICIAN, term="Уборка")
    world.catalog.similar["уборка"] = ELECTRICIAN

    results = await world.run("уборка")

    assert results.page.items == ()
    assert world.stages() == [Stage.TAXONOMY, Stage.ALL_WORDS, Stage.PREFIX, Stage.ANY_WORD]


async def test_nothing_found_is_logged_and_hinted() -> None:
    world = World()
    filters = SpecialistFilters(city_id=CITY, available_today=True, languages=("sr",))

    results = await world.run("qwerty", filters=filters, locale="sr-Latn")
    assert world.log.entries == []  # журнал пишет вызывающий после ответа
    assert results.zero_result is not None
    await world.use_case.record(results.zero_result)

    assert results.hints == ("relax_filters", "post_job")
    [entry] = world.log.entries
    assert (entry.q, entry.locale, entry.city_id, entry.filters) == (
        "qwerty",
        "sr-Latn",
        CITY,
        ("languages", "available_today"),
    )
    assert world.uow.committed == 1


async def test_empty_browse_is_hinted_but_not_logged() -> None:
    world = World()

    results = await world.run()

    assert (results.hints, results.zero_result) == (("post_job",), None)


async def test_next_page_is_found_by_the_same_stage() -> None:
    world = World()
    world.search.by_stage[Stage.ANY_WORD] = [hit(number) for number in range(25)]

    first = await world.run("ремонт ванной")
    world.search.calls.clear()
    second = await world.run(
        "ремонт ванной", page=PageRequest(limit=20, cursor=first.page.next_cursor)
    )

    assert (len(first.page.items), len(second.page.items)) == (20, 5)
    assert second.page.next_cursor is None
    assert [(call.stage, call.offset) for call in world.search.calls] == [(Stage.ANY_WORD, 20)]


async def test_paging_stops_at_offset_500() -> None:
    world = World()
    world.search.by_stage[Stage.BROWSE] = [hit(number) for number in range(600)]

    cursor = None
    pages = 0
    while True:
        results = await world.run(page=PageRequest(limit=100, cursor=cursor))
        pages += 1
        if results.page.next_cursor is None:
            break
        cursor = results.page.next_cursor

    assert pages == 6  # смещения 0, 100, …, 500 — дальше не листается


async def test_weights_come_from_the_flag() -> None:
    world = World()
    world.flags.values["search.weights"] = {"text": 0.9, "availability": 0.2}

    await world.run()
    await world.run(urgent=True)

    # доступность — только при «Срочно»: иначе перебивала бы совпадение с текстом
    assert [call.weights for call in world.search.calls] == [
        RankWeights(text=0.9, availability=0.0),
        RankWeights(text=0.9, availability=0.2),
    ]


@pytest.mark.parametrize(
    "command",
    [
        {"sort": SpecialistSort.DISTANCE},
        {"filters": SpecialistFilters(city_id=CITY, radius_m=3_000)},
        {"filters": SpecialistFilters(city_id=CITY, travels_to_me=True)},
    ],
)
async def test_distance_needs_the_client_point(command: dict[str, Any]) -> None:
    with pytest.raises(DomainValidationError):
        await World().run(**command)


async def test_card_shows_what_the_client_needs() -> None:
    world = World()
    photo = MediaId(UUID(int=99))
    world.media.files[photo] = MediaRef(
        id=photo,
        kind="image",
        status="ready",
        placeholder="hash",
        variants=(
            MediaVariantRef(name="md", url="https://cdn/md.webp", width=800, height=600),
            MediaVariantRef(name="thumb", url="https://cdn/thumb.webp", width=320, height=240),
        ),
        video_url=None,
        duration_ms=None,
    )
    reviewed = hit(1, rating_bayes=4.6, rating_count=5, distance_m=1_340.0)
    with_photo = hit(2, available_until=NOW + timedelta(hours=3))
    with_photo.card["avatar"] = {"media_id": str(photo), "placeholder": "hash"}  # type: ignore[index]
    stale = hit(3, rating_bayes=5.0, rating_count=2, available_until=NOW - timedelta(minutes=1))
    world.search.by_stage[Stage.BROWSE] = [reviewed, with_photo, stale]

    cards = (await world.run()).page.items

    assert (cards[0].rating, cards[0].is_new, cards[0].distance_m) == (4.6, False, 1_500)
    assert cards[1].avatar is not None
    assert (cards[1].avatar.url, cards[1].avatar.width) == ("https://cdn/thumb.webp", 320)
    assert cards[1].available_until == NOW + timedelta(hours=3)
    assert (cards[2].rating, cards[2].is_new, cards[2].available_until) == (None, True, None)
    assert cards[0].district_name == {"ru": "Лиман", "sr-Cyrl": "Лиман"}
    assert world.media.asked == [frozenset({photo})]
