"""SQL выдачи специалистов на PostgreSQL (DEVELOPMENT_PLAN 4.2; ARCHITECTURE §9.2–9.5).

Строки read-model пишет проектор 4.1 (SqlSpecialistIndex), выдачу читает SqlSpecialistSearch.
Ловушки лаборатории: радиус в метрах по geography (а не в градусах по geometry), `đ` → `dj`
в документе и запросе, «выезжает ко мне» — по радиусу выезда каждого специалиста.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID

import procrastinate
import pytest
from sqlalchemy import Update, update
from sqlalchemy.ext.asyncio import AsyncSession
from tests.plugins.database import make_uow

from app.modules.search.application.dto import SpecialistFilters, SpecialistHit, TextMatch
from app.modules.search.domain.index import IndexEntry, SearchDocument, serbian
from app.modules.search.domain.query import QueryText, RankWeights, SpecialistSort, Stage
from app.modules.search.infrastructure.index import SqlSpecialistIndex
from app.modules.search.infrastructure.models import SpecialistIndexRow
from app.modules.search.infrastructure.search import SqlSpecialistSearch
from app.modules.search.tests.builders import (
    CENTER,
    CITY,
    ELECTRIC,
    FIVE_KM_NORTH,
    NOW,
    PLUMBER,
    PLUMBING,
    REPAIR,
    entry,
)

pytestmark = pytest.mark.integration


class Index:
    def __init__(self, session: AsyncSession, app: procrastinate.App) -> None:
        self.session, self.app = session, app

    async def add(self, *entries: IndexEntry) -> list[UUID]:
        uow = make_uow(self.session, self.app)
        async with uow:
            await SqlSpecialistIndex(self.session, uow).upsert(entries)
        return [item.profile_id for item in entries]

    async def set(self, stmt: Update) -> None:
        """Колонки, которых проектор пока не пишет; commit — иначе чтение выдачи откатит."""
        await self.session.execute(stmt)
        await self.session.commit()

    async def hits(
        self,
        match: TextMatch | None = None,
        *,
        sort: SpecialistSort = SpecialistSort.RELEVANCE,
        **filters: Any,
    ) -> list[SpecialistHit]:
        return await SqlSpecialistSearch(self.session).search(
            SpecialistFilters(city_id=CITY, **filters),
            match,
            sort=sort,
            weights=RankWeights(),
            offset=0,
            limit=50,
            now=NOW,
        )

    async def found(
        self,
        match: TextMatch | None = None,
        *,
        sort: SpecialistSort = SpecialistSort.RELEVANCE,
        **filters: Any,
    ) -> list[UUID]:
        return [hit.profile_id for hit in await self.hits(match, sort=sort, **filters)]


@pytest.fixture
def index(db_session: AsyncSession, procrastinate_app: procrastinate.App) -> Index:
    return Index(db_session, procrastinate_app)


def badge(profile_id: UUID, name: str) -> Update:
    """Бейджи заполнит v1 — в тесте прямым UPDATE."""
    row = SpecialistIndexRow
    return update(row).where(row.profile_id == profile_id).values(badges=[name])


def rating(profile_id: UUID, bayes: float, count: int) -> Update:
    """Рейтинг заполнит 7.2 — в тесте прямым UPDATE."""
    row = SpecialistIndexRow
    return (
        update(row)
        .where(row.profile_id == profile_id)
        .values(rating_bayes=bayes, rating_lower_bound=bayes - 0.5, rating_count=count)
    )


def text(q: str, stage: Stage = Stage.ALL_WORDS) -> TextMatch:
    parsed = QueryText.parse(q)
    assert parsed is not None
    return TextMatch(stage=stage, fts=parsed.fts(stage), name=parsed.raw)


async def test_query_shows_listed_pros_unless_casual_is_asked(index: Index) -> None:
    pro, casual, hidden = await index.add(
        entry("Pro"),
        entry("Casual", kind="casual"),
        entry("Hidden", is_listed=False),
    )

    assert await index.found() == [pro]
    assert await index.found(kind="casual") == [casual]
    assert hidden not in await index.found(kind="pro")


async def test_query_category_includes_its_subcategories(index: Index) -> None:
    electrician, plumber = await index.add(
        entry("A"), entry("B", category_ids=(REPAIR, PLUMBING), document=PLUMBER)
    )

    assert await index.found(category_id=ELECTRIC) == [electrician]
    assert set(await index.found(category_id=REPAIR)) == {electrician, plumber}


@pytest.mark.parametrize("q", ["электрик", "električar", "elektricar", "електричар", "Electrician"])
async def test_query_finds_the_same_specialist_in_any_language_and_script(
    index: Index, q: str
) -> None:
    electrician, _ = await index.add(entry("A"), entry("B", document=PLUMBER))

    assert await index.found(text(q)) == [electrician]


@pytest.mark.parametrize("q", ["građevinski", "gradjevinski", "грађевински", "Građevinski radovi"])
async def test_query_dj_is_spelled_out_in_query_and_document(index: Index, q: str) -> None:
    builder = SearchDocument(names_sr=serbian("Građevinski radovi ; Грађевински радови"))
    [found] = await index.add(entry("A", document=builder))

    assert await index.found(text(q)) == [found]


async def test_query_relaxes_to_word_starts_and_then_to_any_word(index: Index) -> None:
    chandeliers = SearchDocument(names_sr="Električar", prices="Montaža lustera")
    electrician, plumber = await index.add(
        entry("A", document=chandeliers), entry("B", document=PLUMBER)
    )

    assert await index.found(text("lust")) == []
    assert await index.found(text("lust", Stage.PREFIX)) == [electrician]
    assert await index.found(text("električar vodoinstalater")) == []
    assert set(await index.found(text("električar vodoinstalater", Stage.ANY_WORD))) == {
        electrician,
        plumber,
    }


async def test_query_finds_a_name_with_a_typo(index: Index) -> None:
    marko, _ = await index.add(entry("Marko Petrović"), entry("Erik Novak"))

    assert await index.found(text("Marko Petrovi")) == [marko]
    assert await index.found(text("электрик")) != [marko]  # «Erik» не похож на «электрик»


async def test_query_radius_is_in_meters_on_geography(index: Index) -> None:
    near, far = await index.add(
        entry("Near"),
        entry("Far", base_point=FIVE_KM_NORTH, base_point_public=FIVE_KM_NORTH),
    )

    # geometry(4326) мерил бы градусы: радиус 3 000 «градусов» накрыл бы всех
    assert await index.found(point=CENTER, radius_m=3_000) == [near]
    assert set(await index.found(point=CENTER, radius_m=10_000)) == {near, far}
    [far_hit] = [hit for hit in await index.hits(point=CENTER) if hit.profile_id == far]
    assert far_hit.distance_m is not None
    assert 4_900 < far_hit.distance_m < 5_100


async def test_query_travels_to_me_by_each_specialist_radius(index: Index) -> None:
    at_five_km = {"base_point": FIVE_KM_NORTH, "base_point_public": FIVE_KM_NORTH}
    short, default, at_home = await index.add(
        entry("Short", travel_radius_m=3_000, **at_five_km),
        entry("Default", travel_radius_m=None, **at_five_km),
        entry("Home", travel_radius_m=10_000, work_modes=("at_own_place",), **at_five_km),
    )

    found = await index.found(point=CENTER, travels_to_me=True)

    assert found == [default]  # без радиуса — 30 км; у себя принимает — не выезжает
    assert short not in found
    assert at_home not in found


async def test_query_price_in_a_category_uses_its_own_price(index: Index) -> None:
    cheap_elsewhere, fair = await index.add(
        entry("A", price_from=100_000, category_prices={ELECTRIC: 300_000, PLUMBING: 100_000}),
        entry("B", price_from=200_000, category_prices={ELECTRIC: 200_000}),
    )

    assert set(await index.found(price_max=250_000)) == {cheap_elsewhere, fair}
    [hit] = await index.hits(price_max=250_000, category_id=ELECTRIC)
    assert (hit.profile_id, hit.price_from) == (fair, 200_000)


async def test_query_profile_filters(index: Index) -> None:
    serbian_speaker, available, reviewed, verified, remote = await index.add(
        entry("Sr", languages=("sr",)),
        entry("Now", available_until=NOW + timedelta(hours=2)),
        entry("Rated"),
        entry("Phone"),
        entry("Remote", work_modes=("remote",)),
    )
    await index.set(badge(verified, "phone_verified"))
    await index.set(rating(reviewed, 4.7, 4))

    assert await index.found(languages=("sr",)) == [serbian_speaker]
    assert await index.found(available_today=True) == [available]
    assert await index.found(with_reviews=True) == [reviewed]
    assert await index.found(rating_min=4.5) == [reviewed]
    assert await index.found(verified=True) == [verified]
    assert await index.found(work_modes=("remote",)) == [remote]


async def test_query_sorts(index: Index) -> None:
    cheap, pricey, no_price = await index.add(
        entry("Cheap", price_from=50_000, activity_score=0.1),
        entry(
            "Pricey",
            price_from=90_000,
            activity_score=0.9,
            base_point=FIVE_KM_NORTH,
            base_point_public=FIVE_KM_NORTH,
        ),
        entry("Free", price_from=None, activity_score=0.5),
    )
    await index.set(rating(cheap, 4.9, 10))

    assert await index.found(sort=SpecialistSort.PRICE) == [cheap, pricey, no_price]
    assert (await index.found(sort=SpecialistSort.RATING))[0] == cheap
    # рейтинг весит больше активности; без рейтинга порядок решает активность
    assert await index.found(sort=SpecialistSort.RELEVANCE) == [cheap, pricey, no_price]
    assert (await index.found(sort=SpecialistSort.DISTANCE, point=CENTER))[-1] == pricey


async def test_query_count_follows_filters_and_stops_at_the_cap(index: Index) -> None:
    await index.add(*(entry(f"M{number}") for number in range(5)), entry("Sr", languages=("sr",)))
    search = SqlSpecialistSearch(index.session)
    filters = SpecialistFilters(city_id=CITY)

    assert await search.count(filters, None, now=NOW, cap=100) == 6
    assert await search.count(filters, None, now=NOW, cap=3) == 3
    by_language = SpecialistFilters(city_id=CITY, languages=("sr",))
    assert await search.count(by_language, None, now=NOW, cap=100) == 1
    assert await search.count(filters, text("vodoinstalater"), now=NOW, cap=100) == 0


async def test_query_counts_by_category_include_subcategories(index: Index) -> None:
    await index.add(
        entry("A"),
        entry("B"),
        entry("C", category_ids=(REPAIR, PLUMBING), document=PLUMBER),
        entry("Casual", kind="casual"),
        entry("Hidden", is_listed=False),
    )

    counts = await SqlSpecialistSearch(index.session).count_by_category(CITY, "pro")

    assert counts == {REPAIR: 3, ELECTRIC: 2, PLUMBING: 1}
