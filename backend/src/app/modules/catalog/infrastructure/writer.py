"""Импорт таксономии из сидов: upsert по slug, неизменённые категории не трогаются (seed_hash).

- Единица импорта — категория вместе с тегами и словарём. Хэш считается по ней и по
  цепочке slug предков: перенос раздела меняет `path` потомков, и они тоже «обновлены».
- `path` и `depth` пишет триггер БД (catalog_0001), код их не передаёт. CHECK глубины не
  откладывается, поэтому импорт идёт в два прохода: сначала отцепляет категории, у которых
  меняется родитель (`parent_id = NULL` пути только укорачивает), затем пишет сверху вниз.
  Промежуточное дерево не глубже итогового, и результат не зависит от порядка в YAML.
- Итоговую глубину импорт проверяет до записи — вместе с категориями, которых нет в сиде:
  перенос предка может опустить их ниже MAX_DEPTH, и ошибка называет такую категорию.
- Словарь категории принадлежит сидам: при изменении категории её строки search_terms
  заменяются целиком, а теги, которых больше нет в сиде, выключаются (`is_active`) — после
  записи всех категорий, чтобы тег, перенесённый сидом в другую категорию, остался как был.
  Включён ли тег, сид задаёт только при вставке: выключенный админкой тег правка сида не
  включает, а тег, который вернулся в сид, включает админка.
- Категорий, которых нет в сиде, импорт не трогает: выключает их админка (2.7b).
- Настройки модерации: `is_active` сид задаёт только при вставке (по умолчанию из БД),
  `risk_level` при обновлении только повышает. Выключенная или запрещённая админкой
  категория такой и остаётся после любой правки сида; снижает риск только админка.
- Порядок и иконку категории (`sort_order`, `icon`) сид тоже задаёт только при вставке:
  дальше их ведёт админка (2.7b), и правка категории в сиде их не возвращает.
- `jobs_enabled` и `max_responses` сиды не задают: при вставке — значения по умолчанию
  из БД, дальше их меняет админка.
- Название категории или тега, поправленное в админке (`name_origin = admin`, 2.7b), импорт
  оставляет как есть. Словарь поиска по-прежнему строится из названия и синонимов сида:
  прежнее название остаётся поисковым термином, новое ищется, когда его добавят в сид синонимом.
"""

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy import case, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.application.dto import CategorySeed, ImportResult
from app.modules.catalog.domain.category import MAX_DEPTH
from app.modules.catalog.domain.terms import SearchTerm, dictionary
from app.modules.catalog.errors import CategoryTooDeepError
from app.modules.catalog.infrastructure.models import (
    IMPORT_LOCK,
    CategoryRow,
    SearchTermRow,
    TagRow,
    price_hints_json,
)
from app.platform.db.constraints import ConstraintErrors, raise_domain_error
from app.platform.db.port import UnitOfWork
from app.platform.db.types import NameOrigin
from app.platform.kernel.ids import CategoryId
from app.platform.kernel.localized import LocalizedText

CATEGORY_CONSTRAINTS: ConstraintErrors = {
    "ck_categories_depth": lambda: CategoryTooDeepError(max_depth=MAX_DEPTH),
}


def _hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _terms(terms: Sequence[SearchTerm]) -> list[list[object]]:
    return [[term.locale.value, term.text, term.weight] for term in terms]


@dataclass(frozen=True, slots=True, kw_only=True)
class _Planned:
    """Категория сида, готовая к записи: локали, словарь и хэш уже посчитаны."""

    seed: CategorySeed
    parent: str | None
    """slug родителя в сиде."""
    name: LocalizedText
    tags: tuple[tuple[str, LocalizedText], ...]
    terms: tuple[SearchTerm, ...]
    seed_hash: str


@dataclass(frozen=True, slots=True, kw_only=True)
class _Stored:
    id: int
    parent: str | None
    """slug родителя в БД."""
    seed_hash: str | None


@dataclass
class _Counts:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    changed: list[CategoryId] = field(default_factory=list)


def _plan(seeds: Sequence[CategorySeed], ancestors: tuple[str, ...] = ()) -> Iterator[_Planned]:
    """Сверху вниз: родитель всегда раньше потомков."""
    for seed in seeds:
        name = seed.name.with_sr_latn()
        tags = tuple((tag.slug, tag.name.with_sr_latn()) for tag in seed.tags)
        terms = dictionary(name, seed.synonyms)
        seed_hash = _hash(
            [
                list(ancestors),
                seed.slug,
                name.to_mapping(),
                seed.icon,
                seed.sort_order,
                int(seed.risk_level),
                price_hints_json(seed.price_hints),
                [[slug, tag_name.to_mapping()] for slug, tag_name in tags],
                _terms(terms),
            ]
        )
        yield _Planned(
            seed=seed,
            parent=ancestors[-1] if ancestors else None,
            name=name,
            tags=tags,
            terms=terms,
            seed_hash=seed_hash,
        )
        yield from _plan(seed.children, (*ancestors, seed.slug))


def _seed_name(row: type[CategoryRow] | type[TagRow], proposed: object) -> object:
    """Название из сида, если его не поправили в админке (`name_origin = admin`)."""
    return case((row.name_origin == NameOrigin.ADMIN, row.name), else_=proposed)


def _too_deep(parents: Mapping[str, str | None]) -> str | None:
    """Первая категория, которая в итоговом дереве глубже MAX_DEPTH; цикл — тоже."""
    for slug in parents:
        node: str | None = slug
        for _ in range(MAX_DEPTH):
            node = parents[node] if node is not None else None
        if node is not None:
            return slug
    return None


class SqlCatalogWriter:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def import_taxonomy(self, categories: Sequence[CategorySeed]) -> ImportResult:
        self._uow.require_active()
        # правка справочника в админке (2.7b) берёт тот же ключ: импорт её не перетрёт
        await self._session.execute(select(func.pg_advisory_xact_lock(IMPORT_LOCK)))
        planned = list(_plan(categories))
        stored = await self._stored()
        changed = [
            p
            for p in planned
            if (s := stored.get(p.seed.slug)) is None or s.seed_hash != p.seed_hash
        ]
        # Неизменённые категории и категории вне сида остаются у своего родителя в БД.
        parents = {slug: s.parent for slug, s in stored.items()}
        parents.update((p.seed.slug, p.parent) for p in changed)
        if (slug := _too_deep(parents)) is not None:
            raise CategoryTooDeepError(max_depth=MAX_DEPTH, slug=slug)
        await self._detach(
            [
                s.id
                for p in changed
                if (s := stored.get(p.seed.slug)) is not None and s.parent != p.parent
            ]
        )
        counts = _Counts()
        ids: dict[str, int] = {}
        for p in planned:
            existing = stored.get(p.seed.slug)
            if existing is not None and existing.seed_hash == p.seed_hash:
                counts.unchanged += 1
                ids[p.seed.slug] = existing.id
                continue
            # Родитель уже записан проходом выше, и триггер берёт его path.
            parent_id = ids[p.parent] if p.parent is not None else None
            category_id = await self._upsert(p, parent_id)
            ids[p.seed.slug] = category_id
            await self._replace_contents(category_id, p.tags, p.terms)
            if existing is None:
                counts.created += 1
            else:
                counts.updated += 1
            counts.changed.append(CategoryId(category_id))
        await self._deactivate_dropped_tags(
            counts.changed, sorted({slug for p in planned for slug, _ in p.tags})
        )
        return ImportResult(
            created=counts.created,
            updated=counts.updated,
            unchanged=counts.unchanged,
            changed=tuple(counts.changed),
        )

    async def _stored(self) -> dict[str, _Stored]:
        """Всё дерево из БД: справочник — десятки и сотни строк."""
        c = CategoryRow.__table__.c
        parent = CategoryRow.__table__.alias("parent")
        rows = await self._session.execute(
            select(c.id, c.slug, c.seed_hash, parent.c.slug.label("parent"))
            .select_from(CategoryRow.__table__.outerjoin(parent, parent.c.id == c.parent_id))
            .order_by(c.id)
        )
        return {
            row.slug: _Stored(id=row.id, parent=row.parent, seed_hash=row.seed_hash) for row in rows
        }

    async def _detach(self, category_ids: Sequence[int]) -> None:
        """Первый проход: категории, что сменят родителя, временно становятся корнями."""
        if category_ids:
            await self._session.execute(
                update(CategoryRow).where(CategoryRow.id.in_(category_ids)).values(parent_id=None)
            )

    async def _upsert(self, planned: _Planned, parent_id: int | None) -> int:
        seed = planned.seed
        values = {
            "parent_id": parent_id,
            "name": planned.name,
            "price_hint": seed.price_hints,
            "seed_hash": planned.seed_hash,
        }
        # icon и sort_order — только в новую строку: у существующей их ведёт админка
        row = pg_insert(CategoryRow).values(
            slug=seed.slug,
            risk_level=int(seed.risk_level),
            icon=seed.icon,
            sort_order=seed.sort_order,
            **values,
        )
        upsert = row.on_conflict_do_update(
            index_elements=["slug"],
            set_={
                **values,
                "name": _seed_name(CategoryRow, row.excluded.name),
                "risk_level": func.greatest(CategoryRow.risk_level, row.excluded.risk_level),
            },
        ).returning(CategoryRow.id)
        try:
            return int((await self._session.execute(upsert)).scalar_one())
        except IntegrityError as err:
            raise_domain_error(err, CATEGORY_CONSTRAINTS)

    async def _replace_contents(
        self,
        category_id: int,
        tags: Sequence[tuple[str, LocalizedText]],
        terms: Sequence[SearchTerm],
    ) -> None:
        """Теги категории и её словарь — как в сиде; включён ли тег, решает админка."""
        rows = [self._term_row(category_id, None, term) for term in terms]
        for slug, tag_name in tags:
            values = {"category_id": category_id, "name": tag_name}
            row = pg_insert(TagRow).values(slug=slug, is_active=True, **values)
            upsert = row.on_conflict_do_update(
                index_elements=["slug"],
                set_={**values, "name": _seed_name(TagRow, row.excluded.name)},
            ).returning(TagRow.id)
            tag_id = int((await self._session.execute(upsert)).scalar_one())
            rows += [self._term_row(category_id, tag_id, term) for term in dictionary(tag_name)]
        await self._session.execute(
            delete(SearchTermRow).where(SearchTermRow.category_id == category_id)
        )
        await self._session.execute(insert(SearchTermRow), rows)

    async def _deactivate_dropped_tags(
        self, category_ids: Sequence[int], seed_tags: Sequence[str]
    ) -> None:
        """Теги изменённых категорий, которых нет в сиде, выключаются (их термины уже удалены)."""
        if category_ids:
            await self._session.execute(
                update(TagRow)
                .where(
                    TagRow.category_id.in_(category_ids),
                    TagRow.slug.not_in(seed_tags),
                    TagRow.is_active,
                )
                .values(is_active=False)
            )

    @staticmethod
    def _term_row(category_id: int, tag_id: int | None, term: SearchTerm) -> dict[str, object]:
        return {
            "term": term.text,
            "lang": term.locale,
            "category_id": category_id,
            "tag_id": tag_id,
            "weight": term.weight,
        }
