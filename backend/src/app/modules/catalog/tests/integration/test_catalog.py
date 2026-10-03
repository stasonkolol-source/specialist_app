"""Импорт таксономии, дерево и словарь поиска на PostgreSQL (DEVELOPMENT_PLAN 1.3b).

Синтетическая таксономия со slug `t-…`: реальные сиды могут уже лежать в БД сессии
(фикстура catalog_seeded), поэтому тесты смотрят только на свои категории.
"""

from collections.abc import Sequence
from dataclasses import replace

import procrastinate
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from tests.plugins.database import make_uow

from app.modules.catalog.api import CategorySummary, RiskLevel
from app.modules.catalog.application.dto import CategorySeed, CategoryView, ImportResult, TagSeed
from app.modules.catalog.application.facade import CatalogFacade
from app.modules.catalog.application.use_cases.import_catalog import (
    ImportCatalog,
    ImportCatalogCommand,
)
from app.modules.catalog.domain.category import PriceHint, PriceUnit
from app.modules.catalog.domain.terms import SearchTerm, TermLanguage
from app.modules.catalog.errors import CategoryTooDeepError
from app.modules.catalog.infrastructure.cache import CachedCatalogQuery, TaxonomySnapshotCache
from app.modules.catalog.infrastructure.queries import SqlCatalogQuery
from app.modules.catalog.infrastructure.writer import SqlCatalogWriter
from app.platform.contracts.events.catalog import CatalogChanged
from app.platform.kernel.ids import CategoryId
from app.platform.kernel.localized import Locale, LocalizedText
from app.platform.kernel.money import Money
from app.platform.queue.dispatcher import EventRegistry
from app.platform.queue.port import TaskRef
from app.platform.testing.cache import NoSnapshotCache
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
    price_hints={"novi-sad": PriceHint.from_rsd(1000, 4000, PriceUnit.ITEM)},
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
    use_case = ImportCatalog(uow, SqlCatalogWriter(db_session, uow), FakeClock(), NoSnapshotCache())
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


def _find_or_none(nodes: Sequence[CategoryView], slug: str) -> CategoryView | None:
    for node in nodes:
        if node.slug == slug:
            return node
        if (found := _find_or_none(node.children, slug)) is not None:
            return found
    return None


def _find(nodes: Sequence[CategoryView], slug: str) -> CategoryView:
    node = _find_or_none(nodes, slug)
    assert node is not None, f"{slug} is not in the tree"
    return node


async def _path(db_session: AsyncSession, slug: str) -> list[str]:
    """path категории — slug предков и её самой; заодно depth сверяется с длиной path."""
    row = (
        await db_session.execute(
            text(
                "SELECT array(SELECT a.slug FROM unnest(c.path) WITH ORDINALITY AS p(id, n)"
                " JOIN catalog.categories a ON a.id = p.id ORDER BY p.n) AS path, c.depth"
                " FROM catalog.categories c WHERE c.slug = :s"
            ),
            {"s": slug},
        )
    ).one()
    assert row.depth == len(row.path)
    return list(row.path)


def chain(*slugs: str) -> CategorySeed:
    """Цепочка «корень → потомок → …» из синтетических категорий."""
    node: CategorySeed | None = None
    for slug in reversed(slugs):
        node = a_category(slug, names(slug, slug), children=[node] if node else [])
    assert node is not None
    return node


def with_children(parent: CategorySeed, *children: CategorySeed) -> CategorySeed:
    return replace(parent, children=children)


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


@pytest.mark.parametrize("moved_first", [True, False], ids=["moved-first", "moved-last"])
async def test_restructure_does_not_depend_on_yaml_order(
    db_session: AsyncSession, procrastinate_app: procrastinate.App, moved_first: bool
) -> None:
    await _import(db_session, procrastinate_app, [chain("t-r1", "t-m", "t-l")])
    # t-m уходит под новый раздел, а его бывший потомок t-l остаётся в t-r1: по пути
    # сверху вниз t-l не должен на миг оказаться на четвёртом уровне.
    moved = chain("t-r2", "t-x", "t-m")
    stayed = chain("t-r1", "t-l")

    result = await _import(
        db_session, procrastinate_app, [moved, stayed] if moved_first else [stayed, moved]
    )

    assert (result.created, result.updated, result.unchanged) == (2, 2, 1)
    assert await _path(db_session, "t-m") == ["t-r2", "t-x", "t-m"]
    assert await _path(db_session, "t-l") == ["t-r1", "t-l"]


@pytest.mark.parametrize("roots", [("t-d", "t-c"), ("t-c", "t-d")], ids=str)
async def test_leaf_split_off_a_moved_branch_imports_in_any_order(
    db_session: AsyncSession, procrastinate_app: procrastinate.App, roots: tuple[str, str]
) -> None:
    await _import(db_session, procrastinate_app, [chain("t-a", "t-b", "t-c"), chain("t-d")])
    new = {"t-d": chain("t-d", "t-a", "t-b"), "t-c": chain("t-c")}

    await _import(db_session, procrastinate_app, [new[slug] for slug in roots])

    assert await _path(db_session, "t-b") == ["t-d", "t-a", "t-b"]
    assert await _path(db_session, "t-c") == ["t-c"]


async def test_category_left_out_of_the_seed_blocks_a_move_by_name(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    await _import(db_session, procrastinate_app, [chain("t-a", "t-b", "t-c")])

    # t-c из сида убрали, но импорт его не трогает: под перенесённым t-b он был бы 4-м.
    with pytest.raises(CategoryTooDeepError) as error:
        await _import(db_session, procrastinate_app, [chain("t-x", "t-a", "t-b")])

    assert error.value.params == {"max_depth": 3, "slug": "t-c"}
    assert await _path(db_session, "t-c") == ["t-a", "t-b", "t-c"]
    count = await db_session.execute(
        text("SELECT count(*) FROM catalog.categories WHERE slug = 't-x'")
    )
    assert count.scalar_one() == 0


async def test_seed_change_keeps_admin_deactivation_and_raised_risk(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    await _import(db_session, procrastinate_app, taxonomy())
    await db_session.execute(
        text(
            "UPDATE catalog.categories SET is_active = false, risk_level = 2"
            " WHERE slug = 't-lessons'"
        )
    )
    await db_session.commit()  # правка админки — своя транзакция (здесь — savepoint теста)
    # Новый раздел в начале сдвигает sort_order соседей — t-lessons «изменён» сидом, а
    # электрик ещё и уходит в премодерацию по решению сида.
    electrical = replace(ELECTRICAL, risk_level=RiskLevel.PREMODERATION)
    shifted = [
        replace(root, sort_order=root.sort_order + 1) for root in taxonomy(electrical=electrical)
    ]
    result = await _import(
        db_session, procrastinate_app, [a_category("t-new", names("Новое", "Ново")), *shifted]
    )

    lessons = await _summary(db_session, "t-lessons")
    assert lessons.id in result.changed
    assert (lessons.is_active, lessons.risk_level) == (False, RiskLevel.FORBIDDEN)
    electrical_row = await _summary(db_session, "t-electrical")
    assert (electrical_row.is_active, electrical_row.risk_level) == (
        True,
        RiskLevel.PREMODERATION,
    )
    tree = await SqlCatalogQuery(db_session).tree()
    assert _find_or_none(tree, "t-lessons") is None


async def test_direct_parent_change_cascades_to_descendants(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    """Так раздел перенесёт админка (2.7b): одним UPDATE, без импорта."""
    await _import(db_session, procrastinate_app, taxonomy())

    await db_session.execute(
        text(
            "UPDATE catalog.categories SET parent_id ="
            " (SELECT id FROM catalog.categories WHERE slug = 't-lessons')"
            " WHERE slug = 't-home'"
        )
    )

    assert await _path(db_session, "t-home") == ["t-lessons", "t-home"]
    assert await _path(db_session, "t-electrical") == ["t-lessons", "t-home", "t-electrical"]
    assert await _path(db_session, "t-plumbing") == ["t-lessons", "t-home", "t-plumbing"]
    assert await _path(db_session, "t-repairs") == ["t-repairs"]


async def test_cycle_in_the_tree_is_rejected_by_depth_check(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    await _import(db_session, procrastinate_app, taxonomy())

    with pytest.raises(IntegrityError, match="ck_categories_depth"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "UPDATE catalog.categories SET parent_id ="
                    " (SELECT id FROM catalog.categories WHERE slug = 't-home')"
                    " WHERE slug = 't-repairs'"
                )
            )

    assert await _path(db_session, "t-electrical") == ["t-repairs", "t-home", "t-electrical"]


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


async def test_cached_taxonomy_matches_database_and_sees_new_categories(
    db_session: AsyncSession, db_connection: AsyncConnection, procrastinate_app: procrastinate.App
) -> None:
    """Снимок в памяти процесса отдаёт то же, что база; категория, добавленная после снимка,
    находится по id запросом, а в дереве появляется после сброса (импорт в процессе)."""
    await _import(db_session, procrastinate_app, taxonomy())
    maker = async_sessionmaker(bind=db_connection, join_transaction_mode="create_savepoint")
    cache = TaxonomySnapshotCache(maker)
    sql = SqlCatalogQuery(db_session)
    cached = CachedCatalogQuery(cache, sql)
    slugs = ("t-lessons", "t-home", "t-electrical")
    ids = [(await _summary(db_session, slug)).id for slug in slugs]

    assert await cached.tree() == await sql.tree()
    assert await cached.categories(ids) == await sql.categories(ids)
    assert "novi-sad" in await cached.price_hint_cities()

    late_seed = a_category("t-late", names("Позже", "Касније"))
    await _import(db_session, procrastinate_app, [*taxonomy(), late_seed])
    late = await _summary(db_session, "t-late")
    assert await cached.category(late.id) == late
    assert _find_or_none(await cached.tree(), "t-late") is None
    cache.invalidate()
    assert _find(await cached.tree(), "t-late").slug == "t-late"


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


async def test_query_is_matched_whole_or_by_prefix(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    await _import(db_session, procrastinate_app, taxonomy())
    facade = CatalogFacade(SqlCatalogQuery(db_session))
    electrical = (await _summary(db_session, "t-electrical")).id

    whole = await facade.match_query("Електричар")
    prefix = await facade.match_query("электр")

    assert whole is not None
    assert (whole.exact, electrical in whole.category_ids) == (True, True)
    assert prefix is not None
    assert (prefix.exact, electrical in prefix.category_ids) == (False, True)
    # префикс короче трёх букв не узнаётся: слишком общий
    assert await facade.match_query("зз") is None
    assert await facade.match_query("   ") is None


async def test_word_of_a_section_and_its_service_matches_the_service(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    electrical = a_category(
        "t-electrical",
        names("Электрик", "Електричар"),
        synonyms=[(TermLanguage.SR, "majstor"), (TermLanguage.SR, "električar")],
    )
    await _import(db_session, procrastinate_app, taxonomy(electrical=electrical))
    facade = CatalogFacade(SqlCatalogQuery(db_session))

    found = await facade.match_query("majstor")

    assert found is not None
    assert (await _summary(db_session, "t-electrical")).id in found.category_ids
    assert (await _summary(db_session, "t-repairs")).id not in found.category_ids


async def test_forbidden_category_is_not_matched(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    await _import(db_session, procrastinate_app, taxonomy())
    facade = CatalogFacade(SqlCatalogQuery(db_session))
    weapons = (await _summary(db_session, "t-weapons")).id

    found = await facade.match_query("Оружие")

    assert found is None or weapons not in found.category_ids


async def test_misspelled_query_gets_the_nearest_term(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    await _import(db_session, procrastinate_app, taxonomy())
    facade = CatalogFacade(SqlCatalogQuery(db_session))

    near = await facade.similar_term("vodoinstaltr")
    near_cyrillic = await facade.similar_term("водоинсталатр")

    # то же слово словаря, но тем алфавитом, каким набран запрос
    assert near is not None
    assert (near.term, near.exact) == ("Vodoinstalater", False)  # название важнее синонима
    assert near_cyrillic is not None
    assert near_cyrillic.term == "Водоинсталатер"
    assert await facade.similar_term("qqqqzzzz") is None


@pytest.mark.parametrize(
    ("typed", "term"), [("elek", "Električar"), ("элек", "Электрик"), ("елек", "Електричар")]
)
async def test_suggestions_by_word_start_in_three_scripts(
    db_session: AsyncSession, procrastinate_app: procrastinate.App, typed: str, term: str
) -> None:
    await _import(db_session, procrastinate_app, taxonomy())
    facade = CatalogFacade(SqlCatalogQuery(db_session))
    electrical = (await _summary(db_session, "t-electrical")).id

    found = await facade.suggest(typed, limit=8)

    ids = [item.category_id for item in found]
    assert len(ids) == len(set(ids)) <= 8  # одна строка на категорию
    [ours] = [item for item in found if item.category_id == electrical]
    assert (ours.fuzzy, ours.name.get(Locale.RU)) == (False, "Электрик")
    assert ours.term == term  # тем алфавитом, каким набран ввод


@pytest.mark.parametrize("typed", ["vodoinstaltr", "водоинсталатр", "сантехнк"])
async def test_typos_are_suggested_by_similarity(
    db_session: AsyncSession, procrastinate_app: procrastinate.App, typed: str
) -> None:
    await _import(db_session, procrastinate_app, taxonomy())
    facade = CatalogFacade(SqlCatalogQuery(db_session))
    plumbing = (await _summary(db_session, "t-plumbing")).id

    found = await facade.suggest(typed, limit=8)

    assert [item.fuzzy for item in found if item.category_id == plumbing] == [True]


async def test_short_input_and_forbidden_categories_get_no_suggestions(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    await _import(db_session, procrastinate_app, taxonomy())
    facade = CatalogFacade(SqlCatalogQuery(db_session))
    weapons = (await _summary(db_session, "t-weapons")).id

    assert await facade.suggest("э", limit=8) == []
    assert weapons not in [item.category_id for item in await facade.suggest("оруж", limit=8)]
    assert len(await facade.suggest("ре", limit=2)) <= 2
