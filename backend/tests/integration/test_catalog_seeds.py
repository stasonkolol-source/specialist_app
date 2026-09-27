"""Реальная таксономия пилота в PostgreSQL (DEVELOPMENT_PLAN 1.3b).

Каждый синоним и каждое название из сидов находит свою категорию по ключу `norm` — как
написано, в латинице (для кириллицы) и без диакритики: так пишут на телефоне без
сербской раскладки.
"""

import unicodedata
from collections.abc import Iterator

import procrastinate
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.entrypoints.seeds import load_catalog_seed
from app.modules.catalog.application.dto import CategorySeed, ImportResult
from app.modules.catalog.application.use_cases.import_catalog import (
    ImportCatalog,
    ImportCatalogCommand,
)
from app.modules.catalog.domain.terms import SearchTerm, dictionary
from app.modules.catalog.infrastructure.writer import SqlCatalogWriter
from app.platform.kernel.localized import Locale
from app.platform.kernel.translit import sr_cyrl_to_latn
from app.platform.testing.clock import FakeClock
from tests.plugins.database import make_uow

pytestmark = pytest.mark.integration


def _walk(categories: tuple[CategorySeed, ...] | list[CategorySeed]) -> Iterator[CategorySeed]:
    for category in categories:
        yield category
        yield from _walk(category.children)


def _spellings(term: SearchTerm) -> set[str]:
    """Как ещё напишут сербское слово: латиницей вместо кириллицы и без диакритики (đ → dj)."""
    if term.locale not in {Locale.SR_CYRL, Locale.SR_LATN}:
        return {term.text}
    latin = sr_cyrl_to_latn(term.text)
    plain = unicodedata.normalize("NFKD", latin.replace("đ", "dj").replace("Đ", "Dj"))
    return {term.text, latin, "".join(ch for ch in plain if not unicodedata.combining(ch))}


async def _import(db_session: AsyncSession, app: procrastinate.App) -> ImportResult:
    uow = make_uow(db_session, app)
    use_case = ImportCatalog(uow, SqlCatalogWriter(db_session, uow), FakeClock())
    return await use_case(ImportCatalogCommand(categories=tuple(load_catalog_seed())))


async def test_second_import_changes_nothing(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    first = await _import(db_session, procrastinate_app)
    second = await _import(db_session, procrastinate_app)
    assert first.created + first.updated + first.unchanged == 18
    assert (second.created, second.updated, second.unchanged, second.changed) == (0, 0, 18, ())
    depths = await db_session.execute(
        text("SELECT depth, count(*) FROM catalog.categories GROUP BY depth ORDER BY depth")
    )
    assert depths.all() == [(1, 5), (2, 13)]


async def test_every_seed_term_finds_its_category_by_norm(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    await _import(db_session, procrastinate_app)
    missing = []
    for category in _walk(load_catalog_seed()):
        names = [category.name.with_sr_latn(), *(tag.name.with_sr_latn() for tag in category.tags)]
        terms = [term for name in names for term in dictionary(name)]
        for term in [*terms, *category.synonyms]:
            for spelling in _spellings(term):
                found = await db_session.execute(
                    text(
                        "SELECT c.slug FROM catalog.search_terms t"
                        " JOIN catalog.categories c ON c.id = t.category_id"
                        " WHERE t.norm = platform.search_norm(:q)"
                    ),
                    {"q": spelling},
                )
                if category.slug not in found.scalars().all():
                    missing.append((category.slug, spelling))
    assert missing == []


@pytest.mark.parametrize(
    ("query", "slug"),
    [
        ("электрик", "electrical"),
        ("električar", "electrical"),
        ("elektricar", "electrical"),
        ("Електричар", "electrical"),
        ("electrician", "electrical"),
        ("струја", "electrical"),
        ("мајстор", "handyman"),
        ("majstor", "handyman"),
        ("čišćenje", "cleaning"),
        ("ciscenje", "cleaning"),
        ("чишћење", "cleaning"),
        ("селидба", "moving"),
        ("srpski jezik", "serbian-language"),
        ("српски језик", "serbian-language"),
        ("маникир", "nails"),
        ("manikir", "nails"),
    ],
)
async def test_same_word_in_every_script_reaches_one_category(
    db_session: AsyncSession, procrastinate_app: procrastinate.App, query: str, slug: str
) -> None:
    await _import(db_session, procrastinate_app)
    found = await db_session.execute(
        text(
            "SELECT DISTINCT c.slug FROM catalog.search_terms t"
            " JOIN catalog.categories c ON c.id = t.category_id"
            " WHERE t.norm = platform.search_norm(:q)"
        ),
        {"q": query},
    )
    assert slug in found.scalars().all()
