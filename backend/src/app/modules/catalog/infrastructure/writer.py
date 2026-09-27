"""Импорт таксономии из сидов: upsert по slug, неизменённые категории не трогаются (seed_hash).

- Единица импорта — категория вместе с тегами и словарём. Хэш считается по ней и по
  цепочке slug предков: перенос раздела меняет `path` потомков, и они тоже «обновлены».
- `path` и `depth` пишет триггер БД (catalog_0001), код их не передаёт.
- Словарь категории принадлежит сидам: при изменении категории её строки search_terms
  заменяются целиком, а теги, которых больше нет в сиде, выключаются (`is_active`).
- Категорий, которых нет в сиде, импорт не трогает: выключает их админка (2.7b).
- `jobs_enabled` и `max_responses` сиды не задают: при вставке — значения по умолчанию
  из БД, дальше их меняет админка.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.application.dto import CategorySeed, ImportResult
from app.modules.catalog.domain.category import MAX_DEPTH
from app.modules.catalog.domain.terms import SearchTerm, dictionary
from app.modules.catalog.errors import CategoryTooDeepError
from app.modules.catalog.infrastructure.models import (
    CategoryRow,
    SearchTermRow,
    TagRow,
    price_hints_json,
)
from app.platform.db.constraints import ConstraintErrors, raise_domain_error
from app.platform.db.port import UnitOfWork
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


@dataclass
class _Counts:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    changed: list[CategoryId] = field(default_factory=list)


class SqlCatalogWriter:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session = session
        self._uow = uow

    async def import_taxonomy(self, categories: Sequence[CategorySeed]) -> ImportResult:
        self._uow.require_active()
        counts = _Counts()
        await self._import_level(categories, parent_id=None, ancestors=(), counts=counts)
        return ImportResult(
            created=counts.created,
            updated=counts.updated,
            unchanged=counts.unchanged,
            changed=tuple(counts.changed),
        )

    async def _import_level(
        self,
        seeds: Sequence[CategorySeed],
        *,
        parent_id: int | None,
        ancestors: tuple[str, ...],
        counts: _Counts,
    ) -> None:
        """Сверху вниз: к вставке потомка родитель уже есть, и триггер берёт его path."""
        for seed in seeds:
            category_id = await self._import_category(seed, parent_id, ancestors, counts)
            await self._import_level(
                seed.children,
                parent_id=category_id,
                ancestors=(*ancestors, seed.slug),
                counts=counts,
            )

    async def _import_category(
        self,
        seed: CategorySeed,
        parent_id: int | None,
        ancestors: tuple[str, ...],
        counts: _Counts,
    ) -> int:
        name = seed.name.with_sr_latn()
        tags = [(tag.slug, tag.name.with_sr_latn()) for tag in seed.tags]
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
        c = CategoryRow.__table__.c
        existing = (
            await self._session.execute(select(c.id, c.seed_hash).where(c.slug == seed.slug))
        ).one_or_none()
        if existing is not None and existing.seed_hash == seed_hash:
            counts.unchanged += 1
            return int(existing.id)
        values = {
            "parent_id": parent_id,
            "name": name,
            "icon": seed.icon,
            "sort_order": seed.sort_order,
            "risk_level": int(seed.risk_level),
            "price_hint": seed.price_hints,
            "is_active": True,
            "seed_hash": seed_hash,
        }
        statement = (
            pg_insert(CategoryRow)
            .values(slug=seed.slug, **values)
            .on_conflict_do_update(index_elements=["slug"], set_=values)
            .returning(CategoryRow.id)
        )
        try:
            category_id = int((await self._session.execute(statement)).scalar_one())
        except IntegrityError as err:
            raise_domain_error(err, CATEGORY_CONSTRAINTS)
        await self._replace_contents(category_id, tags, terms)
        if existing is None:
            counts.created += 1
        else:
            counts.updated += 1
        counts.changed.append(CategoryId(category_id))
        return category_id

    async def _replace_contents(
        self,
        category_id: int,
        tags: Sequence[tuple[str, LocalizedText]],
        terms: Sequence[SearchTerm],
    ) -> None:
        """Теги категории и её словарь — ровно как в сиде."""
        rows = [self._term_row(category_id, None, term) for term in terms]
        tag_ids: list[int] = []
        for slug, tag_name in tags:
            values = {"category_id": category_id, "name": tag_name, "is_active": True}
            tag_id = int(
                (
                    await self._session.execute(
                        pg_insert(TagRow)
                        .values(slug=slug, **values)
                        .on_conflict_do_update(index_elements=["slug"], set_=values)
                        .returning(TagRow.id)
                    )
                ).scalar_one()
            )
            tag_ids.append(tag_id)
            rows += [self._term_row(category_id, tag_id, term) for term in dictionary(tag_name)]
        await self._session.execute(
            update(TagRow)
            .where(TagRow.category_id == category_id, TagRow.id.not_in(tag_ids), TagRow.is_active)
            .values(is_active=False)
        )
        await self._session.execute(
            delete(SearchTermRow).where(SearchTermRow.category_id == category_id)
        )
        await self._session.execute(insert(SearchTermRow), rows)

    @staticmethod
    def _term_row(category_id: int, tag_id: int | None, term: SearchTerm) -> dict[str, object]:
        return {
            "term": term.text,
            "lang": term.locale,
            "category_id": category_id,
            "tag_id": tag_id,
            "weight": term.weight,
        }
