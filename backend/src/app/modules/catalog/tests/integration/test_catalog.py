"""Импорт таксономии, дерево и словарь поиска на PostgreSQL (DEVELOPMENT_PLAN 1.3b).

Синтетическая таксономия со slug `t-…`: реальные сиды могут уже лежать в БД сессии
(фикстура catalog_seeded), поэтому тесты смотрят только на свои категории.
"""

from collections.abc import Sequence
from dataclasses import replace

import procrastinate
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.plugins.database import make_uow

from app.modules.catalog.api import CategorySummary, RiskLevel
from app.modules.catalog.application.dto import CategoryNode, CategorySeed, ImportResult, TagSeed
from app.modules.catalog.application.facade import CatalogFacade
from app.modules.catalog.application.use_cases.import_catalog import (
    ImportCatalog,
    ImportCatalogCommand,
)
from app.modules.catalog.domain.category import PriceHint, PriceUnit
from app.modules.catalog.domain.terms import SearchTerm, TermLanguage
from app.modules.catalog.errors import CategoryTooDeepError
from app.modules.catalog.infrastructure.queries import SqlCatalogQuery
from app.modules.catalog.infrastructure.writer import SqlCatalogWriter
from app.platform.contracts.events.catalog import CatalogChanged
from app.platform.kernel.ids import CategoryId
from app.platform.kernel.localized import Locale, LocalizedText
from app.platform.kernel.money import Money
from app.platform.queue.dispatcher import EventRegistry
from app.platform.queue.port import TaskRef
from app.platform.testing.clock import FakeClock
from app.platform.testing.queue import queued_tasks

pytestmark = pytest.mark.integration

ON_CHANGED = TaskRef("test.on_catalog_changed", CatalogChanged)


def names(ru: str, sr_cyrl: str, en: str | None = None) -> LocalizedText:
    values = {Locale.RU: ru, Locale.SR_CYRL: sr_cyrl}
    if en is not None:
        values[Locale.EN] = en
    return LocalizedText(values)


def a_category(
    slug: str,
    name: LocalizedText,
    *,
    children: Sequence[CategorySeed] = (),
    synonyms: Sequence[tuple[TermLanguage, str]] = (),
    tags: Sequence[TagSeed] = (),
    risk_level: RiskLevel = RiskLevel.NORMAL,
    sort_order: int = 0,
    price_hints: dict[str, PriceHint] | None = None,
) -> CategorySeed:
    return CategorySeed(
        slug=slug,
        name=name,
        icon="wrench",
        risk_level=risk_level,
        sort_order=sort_order,
        price_hints=price_hints or {},
        synonyms=tuple(SearchTerm.synonym(text, language) for language, text in synonyms),
        tags=tuple(tags),
        children=tuple(children),
    )


ELECTRICAL = a_category(
    "t-electrical",
    names("Электрик", "Електричар", "Electrician"),
    synonyms=[
        (TermLanguage.RU, "повесить люстру"),
        (TermLanguage.SR, "električar"),
        (TermLanguage.SR, "струја"),
        (TermLanguage.EN, "wiring"),
    ],
    tags=[
        TagSeed(slug="t-chandeliers", name=names("Люстры", "Лустери")),
        TagSeed(slug="t-sockets", name=names("Розетки", "Утичнице")),
    ],
    price_hints={"novi-sad": PriceHint.from_rsd(1000, 4000, PriceUnit.PIECE)},
)
PLUMBING = a_category(
    "t-plumbing",
    names("Сантехник", "Водоинсталатер"),
    synonyms=[(TermLanguage.SR, "vodoinstalater")],
    sort_order=1,
)
FORBIDDEN = a_category(
    "t-weapons", names("Оружие", "Оружје"), risk_level=RiskLevel.FORBIDDEN, sort_order=2
)


def taxonomy(
    *, repairs_name: str = "Ремонт", electrical: CategorySeed = ELECTRICAL
) -> list[CategorySeed]:
    repairs = a_category(
        "t-repairs",
        names(repairs_name, "Поправке"),
        children=[
            a_category("t-home", names("Дом", "Кућа"), children=[electrical, PLUMBING]),
        ],
        synonyms=[(TermLanguage.SR, "majstor")],
    )
    return [repairs, a_category("t-lessons", names("Уроки", "Часови"), sort_order=1), FORBIDDEN]


async def _import(
    db_session: AsyncSession,
    app: procrastinate.App,
    categories: Sequence[CategorySeed],
    registry: EventRegistry | None = None,
) -> ImportResult:
    uow = make_uow(db_session, app, registry)
    use_case = ImportCatalog(uow, SqlCatalogWriter(db_session, uow), FakeClock())
    return await use_case(ImportCatalogCommand(categories=tuple(categories)))


async def _summary(db_session: AsyncSession, slug: str) -> CategorySummary:
    category_id: int = (
        await db_session.execute(
            text("SELECT id FROM catalog.categories WHERE slug = :s"), {"s": slug}
        )
    ).scalar_one()
    summary = await CatalogFacade(SqlCatalogQuery(db_session)).category(CategoryId(category_id))
    assert summary is not None
    return summary


def _find_or_none(nodes: Sequence[CategoryNode], slug: str) -> CategoryNode | None:
    for node in nodes:
        if node.slug == slug:
            return node
        if (found := _find_or_none(node.children, slug)) is not None:
            return found
    return None


def _find(nodes: Sequence[CategoryNode], slug: str) -> CategoryNode:
    node = _find_or_none(nodes, slug)
    assert node is not None, f"{slug} is not in the tree"
    return node


async def test_import_is_idempotent_and_counts_changes(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    first = await _import(db_session, procrastinate_app, taxonomy())
    again = await _import(db_session, procrastinate_app, taxonomy())
    renamed = await _import(db_session, procrastinate_app, taxonomy(repairs_name="Ремонт дома"))

    assert (first.created, first.updated, first.unchanged) == (6, 0, 0)
    assert len(first.changed) == 6
    assert (again.created, again.updated, again.unchanged, again.changed) == (0, 0, 6, ())
    repairs = await _summary(db_session, "t-repairs")
    assert (renamed.created, renamed.updated, renamed.unchanged) == (0, 1, 5)
    assert renamed.changed == (repairs.id,)
    assert repairs.name.to_mapping() == {
        "ru": "Ремонт дома",
        "sr-Cyrl": "Поправке",
        "sr-Latn": "Popravke",
    }


async def test_path_holds_ancestors_and_facade_exposes_moderation_settings(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    await _import(db_session, procrastinate_app, taxonomy())
    repairs, home, electrical = [
        await _summary(db_session, slug) for slug in ("t-repairs", "t-home", "t-electrical")
    ]
    assert repairs.path == (repairs.id,)
    assert home.path == (repairs.id, home.id)
    assert electrical.path == (repairs.id, home.id, electrical.id)
    assert electrical.parent_id == home.id
    assert (electrical.risk_level, electrical.jobs_enabled, electrical.max_responses) == (
        RiskLevel.NORMAL,
        True,
        5,
    )
    assert (await _summary(db_session, "t-weapons")).risk_level is RiskLevel.FORBIDDEN

    facade = CatalogFacade(SqlCatalogQuery(db_session))
    many = await facade.categories([electrical.id, repairs.id, home.id])
    assert [c.slug for c in many] == ["t-repairs", "t-home", "t-electrical"]
    assert await facade.categories([]) == []
    assert await facade.category(CategoryId(2_000_000_000)) is None
    depth = await db_session.execute(
        text("SELECT depth FROM catalog.categories WHERE id = :id"), {"id": electrical.id}
    )
    assert depth.scalar_one() == 3


async def test_moving_a_subtree_rewrites_paths_of_descendants(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    await _import(db_session, procrastinate_app, taxonomy())
    repairs, home, lessons = taxonomy()[0], taxonomy()[0].children[0], taxonomy()[1]
    moved = [replace(repairs, children=()), replace(lessons, children=(home,)), FORBIDDEN]

    result = await _import(db_session, procrastinate_app, moved)

    lessons_id = (await _summary(db_session, "t-lessons")).id
    home_row = await _summary(db_session, "t-home")
    plumbing = await _summary(db_session, "t-plumbing")
    assert home_row.path == (lessons_id, home_row.id)
    assert plumbing.path == (lessons_id, home_row.id, plumbing.id)
    assert (result.created, result.updated, result.unchanged) == (0, 3, 3)
    assert set(result.changed) == {
        home_row.id,
        plumbing.id,
        (await _summary(db_session, "t-electrical")).id,
    }


async def test_tree_deeper_than_three_levels_is_rejected(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    deep = a_category("t-d4", names("Четыре", "Четири"))
    for level in (3, 2, 1):
        deep = a_category(f"t-d{level}", names("Уровень", "Ниво"), children=[deep])

    with pytest.raises(CategoryTooDeepError):
        await _import(db_session, procrastinate_app, [deep])

    count = await db_session.execute(
        text("SELECT count(*) FROM catalog.categories WHERE slug LIKE 't-d_'")
    )
    assert count.scalar_one() == 0


async def test_only_real_changes_emit_catalog_changed(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    registry = EventRegistry()
    registry.subscribe(CatalogChanged, ON_CHANGED)

    first = await _import(db_session, procrastinate_app, taxonomy(), registry)
    await _import(db_session, procrastinate_app, taxonomy(), registry)

    [task] = await queued_tasks(db_session, ON_CHANGED.name)
    assert task.payload["category_ids"] == list(first.changed)
    assert task.queueing_lock is not None


async def test_public_tree_hides_inactive_and_forbidden_categories(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    await _import(db_session, procrastinate_app, taxonomy())
    tree = await SqlCatalogQuery(db_session).tree()

    ours = [node.slug for node in tree if node.slug.startswith("t-")]
    assert ours == ["t-repairs", "t-lessons"]
    home = _find(tree, "t-home")
    assert [child.slug for child in home.children] == ["t-electrical", "t-plumbing"]
    electrical = _find(tree, "t-electrical")
    assert [tag.slug for tag in electrical.tags] == ["t-chandeliers", "t-sockets"]
    assert electrical.price_hints["novi-sad"].min == Money(100_000)
    assert electrical.name.get(Locale.SR_LATN) == "Električar"

    await db_session.execute(
        text("UPDATE catalog.categories SET is_active = false WHERE slug = 't-home'")
    )
    tree = await SqlCatalogQuery(db_session).tree()
    assert _find_or_none(tree, "t-home") is None
    assert _find_or_none(tree, "t-electrical") is None
    assert _find(tree, "t-repairs").children == ()


async def test_seed_owns_tags_and_dictionary_of_its_category(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    await _import(db_session, procrastinate_app, taxonomy())
    trimmed = replace(
        ELECTRICAL,
        tags=ELECTRICAL.tags[:1],
        synonyms=(SearchTerm.synonym("розетка", TermLanguage.RU),),
    )
    await _import(db_session, procrastinate_app, taxonomy(electrical=trimmed))

    tags = await db_session.execute(
        text("SELECT slug, is_active FROM catalog.tags WHERE slug LIKE 't-%' ORDER BY slug")
    )
    assert tags.all() == [("t-chandeliers", True), ("t-sockets", False)]
    terms = await db_session.execute(
        text(
            "SELECT t.term FROM catalog.search_terms t JOIN catalog.categories c"
            " ON c.id = t.category_id WHERE c.slug = 't-electrical' ORDER BY t.id"
        )
    )
    assert terms.scalars().all() == [
        "Электрик",
        "Електричар",
        "Electrician",
        "Električar",
        "розетка",
        "Люстры",
        "Лустери",
        "Lusteri",
    ]


@pytest.mark.parametrize(
    ("query", "slug"),
    [
        ("электрик", "t-electrical"),
        ("ЭЛЕКТРИК", "t-electrical"),
        ("električar", "t-electrical"),
        ("elektricar", "t-electrical"),
        ("електричар", "t-electrical"),
        ("Electrician", "t-electrical"),
        ("struja", "t-electrical"),
        ("струја", "t-electrical"),
        ("lusteri", "t-electrical"),
        ("Водоинсталатер", "t-plumbing"),
        ("vodoinstalater", "t-plumbing"),
        ("мајстор", "t-repairs"),
    ],
)
async def test_every_script_finds_category_by_norm(
    db_session: AsyncSession, procrastinate_app: procrastinate.App, query: str, slug: str
) -> None:
    await _import(db_session, procrastinate_app, taxonomy())
    found = await db_session.execute(
        text(
            "SELECT DISTINCT c.slug FROM catalog.search_terms t"
            " JOIN catalog.categories c ON c.id = t.category_id"
            " WHERE t.norm = platform.search_norm(:q) AND c.slug LIKE 't-%'"
        ),
        {"q": query},
    )
    assert found.scalars().all() == [slug]


async def test_misspelling_is_found_by_trigram_similarity(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    await _import(db_session, procrastinate_app, taxonomy())
    nearest = await db_session.execute(
        text(
            "SELECT c.slug FROM catalog.search_terms t"
            " JOIN catalog.categories c ON c.id = t.category_id"
            " WHERE c.slug LIKE 't-%' AND t.norm % platform.search_norm(:q)"
            " ORDER BY t.norm <-> platform.search_norm(:q) LIMIT 1"
        ),
        {"q": "vodoinstaltr"},
    )
    assert nearest.scalar_one() == "t-plumbing"
