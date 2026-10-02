"""Read-model специалистов в PostgreSQL (§9.3): строки и цены по категориям.

`search_vector` и `name_norm` строит база функциями платформы (platform_0001): русская,
сербская (кириллица → латиница, без диакритики) и английская конфигурации с весами A–D.
Upsert идемпотентен: повтор с той же строкой ничего не меняет по смыслу. Проектор — единственный
писатель строки: все колонки считаются из источников (рейтинг добавит 7.2, продвижение — v1).
"""

from collections.abc import Collection, Mapping, Sequence
from typing import Any, cast
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Table,
    and_,
    bindparam,
    delete,
    func,
    literal_column,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.search.domain.index import IndexEntry, SearchDocument, serbian
from app.modules.search.infrastructure.models import (
    SpecialistCategoryPriceRow,
    SpecialistIndexRow,
)
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CategoryId, UserId


def _concat(*vectors: ColumnElement[Any]) -> ColumnElement[Any]:
    joined = vectors[0]
    for vector in vectors[1:]:
        joined = joined.op("||")(vector)
    return joined


def _weight(vector: ColumnElement[Any], weight: str) -> ColumnElement[Any]:
    # вес — литерал: setweight принимает "char", а параметр пришёл бы как varchar
    return func.setweight(vector, literal_column(f"'{weight}'"))


def _vector(document: SearchDocument) -> ColumnElement[Any]:
    """Документ §9.3: A — имя и категории, B — словарь, C — прайс, D — «о себе»."""
    ru, sr, en = func.platform.tsv_ru, func.platform.tsv_sr, func.platform.tsv_en
    return _concat(
        _weight(_concat(ru(document.names_ru), sr(document.names_sr), en(document.names_en)), "A"),
        _weight(_concat(ru(document.terms_ru), sr(document.terms_sr), en(document.terms_en)), "B"),
        _weight(_concat(ru(document.prices), sr(serbian(document.prices))), "C"),
        _weight(_concat(ru(document.about), sr(serbian(document.about))), "D"),
    )


def _row(entry: IndexEntry) -> dict[str, Any]:
    return {
        "profile_id": entry.profile_id,
        "user_id": entry.user_id,
        "kind": entry.kind,
        "is_listed": entry.is_listed,
        "city_id": entry.city_id,
        "district_id": entry.district_id,
        "district_ids": list(entry.district_ids),
        "base_point": entry.base_point,
        "base_point_public": entry.base_point_public,
        "travel_radius_m": entry.travel_radius_m,
        "category_ids": list(entry.category_ids),
        "languages": list(entry.languages),
        "work_modes": list(entry.work_modes),
        "price_from": entry.price_from,
        "available_until": entry.available_until,
        "activity_score": entry.activity_score,
        "score": entry.score,
        "name_norm": func.platform.search_norm(entry.name),
        "search_vector": _vector(entry.document),
        "card": dict(entry.card),
        "source_updated_at": entry.source_updated_at,
        "indexed_at": func.now(),
    }


class SqlSpecialistIndex:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def upsert(self, entries: Sequence[IndexEntry]) -> None:
        self._uow.require_active()
        if not entries:
            return
        rows = [_row(entry) for entry in entries]
        stmt = insert(SpecialistIndexRow).values(rows)
        # только колонки проектора: рейтинг, время ответа и бейджи пишут свои задачи
        updated = {name: stmt.excluded[name] for name in rows[0] if name != "profile_id"}
        await self._session.execute(
            stmt.on_conflict_do_update(index_elements=["profile_id"], set_=updated)
        )
        await self._replace_prices(entries)

    async def delete(self, profile_ids: Collection[UUID]) -> None:
        self._uow.require_active()
        ids = list(profile_ids)
        if not ids:
            return
        await self._session.execute(
            delete(SpecialistCategoryPriceRow).where(SpecialistCategoryPriceRow.profile_id.in_(ids))
        )
        await self._session.execute(
            delete(SpecialistIndexRow).where(SpecialistIndexRow.profile_id.in_(ids))
        )

    async def _replace_prices(self, entries: Sequence[IndexEntry]) -> None:
        ids = [entry.profile_id for entry in entries]
        await self._session.execute(
            delete(SpecialistCategoryPriceRow).where(SpecialistCategoryPriceRow.profile_id.in_(ids))
        )
        prices = [
            {"profile_id": entry.profile_id, "category_id": category_id, "price_from": price}
            for entry in entries
            for category_id, price in entry.category_prices.items()
        ]
        if prices:
            await self._session.execute(insert(SpecialistCategoryPriceRow).values(prices))

    async def set_response_times(self, minutes: Mapping[UserId, int]) -> None:
        self._uow.require_active()
        table = cast(Table, SpecialistIndexRow.__table__)  # Core: executemany по user_id
        stale: ColumnElement[bool] = table.c.response_time_minutes.is_not(None)
        if minutes:
            stale = and_(stale, table.c.user_id.not_in(list(minutes)))
        await self._session.execute(update(table).where(stale).values(response_time_minutes=None))
        if minutes:
            await self._session.execute(
                update(table)
                .where(table.c.user_id == bindparam("user"))
                .values(response_time_minutes=bindparam("minutes")),
                [{"user": user_id, "minutes": value} for user_id, value in minutes.items()],
            )

    async def response_time(self, profile_id: UUID) -> int | None:
        stmt = select(SpecialistIndexRow.response_time_minutes).where(
            SpecialistIndexRow.profile_id == profile_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def ids_of_users(self, user_ids: Collection[UserId]) -> list[UUID]:
        column = SpecialistIndexRow.profile_id
        stmt = select(column).where(SpecialistIndexRow.user_id.in_(list(user_ids)))
        return list((await self._session.scalars(stmt)).all())

    async def ids_with_categories(self, category_ids: Collection[CategoryId]) -> list[UUID]:
        column = SpecialistIndexRow.profile_id
        stmt = select(column).where(SpecialistIndexRow.category_ids.overlap(list(category_ids)))
        return list((await self._session.scalars(stmt)).all())

    async def ids_after(self, after: UUID | None, *, limit: int) -> list[UUID]:
        column = SpecialistIndexRow.profile_id
        stmt = select(column).order_by(column).limit(limit)
        if after is not None:
            stmt = stmt.where(column > after)
        return list((await self._session.scalars(stmt)).all())
