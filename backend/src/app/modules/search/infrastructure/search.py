"""Выдача специалистов по read-model в PostgreSQL (ARCHITECTURE §9.2–9.5; DEVELOPMENT_PLAN 4.2).

Одна таблица `search.specialist_index` без JOIN по модулям (цены в категории — своя таблица
search). Фильтры §9.5 ложатся на частичные индексы `WHERE is_listed`. Балл §9.4 считается в
SQL; гео — только geography и метры: `ST_DWithin` по geometry(4326) считал бы градусы.
"""

from collections.abc import Collection
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Float,
    and_,
    case,
    cast,
    exists,
    func,
    literal,
    null,
    or_,
    select,
    true,
)

from app.modules.reviews.api import NO_REVIEWS_LOWER_BOUND
from app.modules.search.application.dto import SpecialistFilters, SpecialistHit, TextMatch
from app.modules.search.domain.index import RATING_SCALE
from app.modules.search.domain.query import (
    BADGE_TRUST,
    DISTANCE_SCALE_M,
    FTS_STAGES,
    TRAVEL_DEFAULT_M,
    RankWeights,
    SpecialistSort,
    Stage,
)
from app.modules.search.infrastructure.models import (
    SpecialistCategoryPriceRow,
    SpecialistIndexRow,
)
from app.platform.db.query import SqlQuery
from app.platform.db.types import GeoPointType
from app.platform.kernel.ids import CategoryId, CityId, UserId

AT_CLIENT = "at_client"
PHONE_VERIFIED = "phone_verified"
NAME_SIMILARITY = 0.45
"""Сходство имени по триграммам: ниже — «Erik» находился бы по «электрик»."""
TS_RANK_NORMALIZATION = 32
"""ts_rank_cd / (ts_rank_cd + 1): значения 0..1 для смешивания с другими сигналами (§9.3)."""

_SI = SpecialistIndexRow.__table__.c
_PRICES = SpecialistCategoryPriceRow.__table__.alias("category_price")


class SqlSpecialistSearch(SqlQuery):
    async def search(
        self,
        filters: SpecialistFilters,
        match: TextMatch | None,
        *,
        sort: SpecialistSort,
        weights: RankWeights,
        offset: int,
        limit: int,
        now: datetime,
    ) -> list[SpecialistHit]:
        point = literal(filters.point, GeoPointType) if filters.point is not None else None
        distance = func.ST_Distance(_SI.base_point_public, point) if point is not None else None
        text = _Text(match) if match is not None and match.stage in FTS_STAGES else None
        rank = _rank(weights, text, now)
        if point is not None and distance is not None and sort is SpecialistSort.RELEVANCE:
            rank = rank * func.coalesce(func.exp(-distance / DISTANCE_SCALE_M), 0.0)
        price: ColumnElement[Any] = _SI.price_from
        if filters.category_id is not None:
            price = func.coalesce(_PRICES.c.price_from, _SI.price_from)
        stmt = select(
            _SI.profile_id,
            _SI.card,
            price.label("price_from"),
            _SI.rating_bayes,
            _SI.rating_count,
            _SI.badges,
            _SI.available_until,
            (distance if distance is not None else cast(null(), Float)).label("distance_m"),
        ).where(*_conditions(filters, match, text, point, now))
        if filters.category_id is not None:
            stmt = stmt.select_from(
                SpecialistIndexRow.__table__.outerjoin(
                    _PRICES,
                    and_(
                        _PRICES.c.profile_id == _SI.profile_id,
                        _PRICES.c.category_id == filters.category_id,
                    ),
                )
            )
        stmt = stmt.order_by(*_order(sort, rank, price, point)).offset(offset).limit(limit)
        return [_hit(row) for row in await self._fetch(stmt)]

    async def count(
        self,
        filters: SpecialistFilters,
        match: TextMatch | None,
        *,
        now: datetime,
        cap: int,
    ) -> int:
        point = literal(filters.point, GeoPointType) if filters.point is not None else None
        text = _Text(match) if match is not None and match.stage in FTS_STAGES else None
        matching = (
            select(_SI.profile_id)
            .where(*_conditions(filters, match, text, point, now))
            .limit(cap)
            .subquery()
        )
        row = await self._fetch_one(select(func.count().label("n")).select_from(matching))
        return int(row["n"]) if row is not None else 0

    async def listed(
        self, profile_ids: Collection[UUID], *, hidden_users: Collection[UserId] = ()
    ) -> list[SpecialistHit]:
        if not profile_ids:
            return []
        stmt = select(
            _SI.profile_id,
            _SI.card,
            _SI.price_from,
            _SI.rating_bayes,
            _SI.rating_count,
            _SI.badges,
            _SI.available_until,
            cast(null(), Float).label("distance_m"),
        ).where(_SI.is_listed, _SI.profile_id.in_(list(profile_ids)))
        if hidden_users:
            stmt = stmt.where(_SI.user_id.not_in(list(hidden_users)))
        return [_hit(row) for row in await self._fetch(stmt)]

    async def count_by_category(self, city_id: CityId, kind: str) -> dict[CategoryId, int]:
        # category_ids уже несут предков: строка считается и в разделе, и в подкатегории
        category = func.unnest(_SI.category_ids).table_valued("category_id").render_derived()
        stmt = (
            select(category.c.category_id, func.count().label("n"))
            .select_from(SpecialistIndexRow.__table__.join(category, true()))
            .where(_kind_filter(kind), _SI.city_id == city_id)
            .group_by(category.c.category_id)
        )
        return {CategoryId(row["category_id"]): int(row["n"]) for row in await self._fetch(stmt)}


def _kind_filter(kind: str) -> ColumnElement[bool]:
    """«Подработка» не listed по умолчанию, но доступна по явному фильтру типа.
    Неопубликованные профили и скрытых авторов в индекс не допускает проектор."""
    matching = _SI.kind == kind
    return matching if kind == "casual" else and_(_SI.is_listed, matching)


class _Text:
    """tsquery этапа FTS и ключ имени: фильтр и релевантность — по одному и тому же tsquery."""

    def __init__(self, match: TextMatch) -> None:
        query = (
            func.platform.q_prefix_ru_sr(match.fts)
            if match.stage is Stage.PREFIX
            else func.platform.q_all(match.fts)
        )
        name = func.platform.search_norm(match.name)
        self.condition = or_(
            _SI.search_vector.op("@@")(query),
            and_(
                _SI.name_norm.op("%")(name), func.similarity(_SI.name_norm, name) >= NAME_SIMILARITY
            ),
        )
        self.relevance = func.greatest(
            func.ts_rank_cd(_SI.search_vector, query, TS_RANK_NORMALIZATION),
            func.similarity(_SI.name_norm, name),
        )


def _conditions(
    filters: SpecialistFilters,
    match: TextMatch | None,
    text: _Text | None,
    point: ColumnElement[Any] | None,
    now: datetime,
) -> list[ColumnElement[bool]]:
    found: list[ColumnElement[bool]] = [
        _kind_filter(filters.kind),
        _SI.city_id == filters.city_id,
    ]
    if filters.hidden_users:
        found.append(_SI.user_id.not_in(list(filters.hidden_users)))
    if filters.category_id is not None:
        found.append(_SI.category_ids.overlap([filters.category_id]))
    if match is not None and match.category_ids:
        found.append(_SI.category_ids.overlap(list(match.category_ids)))
    if text is not None:
        found.append(text.condition)
    if filters.district_ids:
        found.append(_SI.district_ids.overlap(list(filters.district_ids)))
    if point is not None and filters.radius_m:
        found.append(func.ST_DWithin(_SI.base_point_public, point, filters.radius_m))
    if point is not None and filters.travels_to_me:
        # константа включает GiST, радиус специалиста уточняет (лаборатория, a11)
        found += [
            _SI.base_point.isnot(None),
            _SI.work_modes.contains([AT_CLIENT]),
            func.ST_DWithin(_SI.base_point, point, TRAVEL_DEFAULT_M),
            func.ST_DWithin(
                _SI.base_point, point, func.coalesce(_SI.travel_radius_m, TRAVEL_DEFAULT_M)
            ),
        ]
    found += _profile_filters(filters, now)
    return found


def _profile_filters(filters: SpecialistFilters, now: datetime) -> list[ColumnElement[bool]]:
    found: list[ColumnElement[bool]] = []
    if filters.price_max is not None:
        if filters.category_id is not None:
            prices = SpecialistCategoryPriceRow.__table__.c
            found.append(
                exists().where(
                    prices.profile_id == _SI.profile_id,
                    prices.category_id == filters.category_id,
                    prices.price_from <= filters.price_max,
                )
            )
        else:
            found.append(_SI.price_from <= filters.price_max)
    if filters.rating_min is not None:
        found.append(_SI.rating_bayes >= filters.rating_min)
    if filters.languages:
        found.append(_SI.languages.overlap(list(filters.languages)))
    if filters.work_modes:
        found.append(_SI.work_modes.overlap(list(filters.work_modes)))
    if filters.available_today:
        found.append(_SI.available_until > now)
    if filters.verified:
        found.append(_SI.badges.contains([PHONE_VERIFIED]))
    if filters.with_reviews:
        found.append(_SI.rating_count > 0)
    return found


def _rank(weights: RankWeights, text: _Text | None, now: datetime) -> ColumnElement[Any]:
    """Балл §9.4, нормированный на сумму участвующих весов: без текста вес текста не в счёт.
    Отзывчивость — с 6.3b: пока сигнала нет, она в балл не входит."""
    # без отзывов — априорная граница: ниже профиля с «пятёркой», выше профиля с «единицей»
    rating = (
        func.coalesce(cast(_SI.rating_lower_bound, Float), NO_REVIEWS_LOWER_BOUND) / RATING_SCALE
    )
    trust = sum(
        (
            case((_SI.badges.contains([badge]), share), else_=0.0)
            for badge, share in BADGE_TRUST.items()
        ),
        start=literal(0.0, Float),
    )
    available = case((_SI.available_until > now, 1.0), else_=0.0)
    parts: list[tuple[float, ColumnElement[Any]]] = [
        (weights.rating, rating),
        (weights.trust, trust),
        (weights.activity, _SI.activity_score),
        (weights.availability, available),
    ]
    if text is not None:
        parts.append((weights.text, text.relevance))
    total = sum(weight for weight, _ in parts) or 1.0
    return sum(
        (literal(weight / total, Float) * signal for weight, signal in parts),
        start=literal(0.0, Float),
    )


def _order(
    sort: SpecialistSort,
    rank: ColumnElement[Any],
    price: ColumnElement[Any],
    point: ColumnElement[Any] | None,
) -> list[ColumnElement[Any]]:
    last: list[ColumnElement[Any]] = [rank.desc(), _SI.profile_id.desc()]
    if sort is SpecialistSort.RATING:
        return [_SI.rating_bayes.desc().nulls_last(), _SI.rating_count.desc(), *last]
    if sort is SpecialistSort.PRICE:
        return [price.asc().nulls_last(), *last]
    if sort is SpecialistSort.DISTANCE and point is not None:
        return [_SI.base_point_public.op("<->")(point).asc().nulls_last(), *last]
    return last


def _hit(row: Any) -> SpecialistHit:
    rating = row["rating_bayes"]
    return SpecialistHit(
        profile_id=row["profile_id"],
        card=row["card"],
        price_from=row["price_from"],
        rating_bayes=float(rating) if rating is not None else None,
        rating_count=row["rating_count"],
        badges=tuple(row["badges"]),
        available_until=row["available_until"],
        distance_m=row["distance_m"],
    )
