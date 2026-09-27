"""Спайк 0.6: SQLAlchemy 2.1 + GeoAlchemy2 0.20 + psycopg 3 на нашем PostGIS.

Проверяем ORM-типы и операторы, которые нужны каталогу, поиску и заявкам
(ARCHITECTURE §7, §9), и влияние plan_cache_mode роли app на prepared statements (ADR-0005).
Итог — docs/spikes/0.6-sqla-geoalchemy.md.
"""

from collections.abc import AsyncIterator

import geoalchemy2
import pytest
import pytest_asyncio
import sqlalchemy
from geoalchemy2 import Geography, Geometry
from sqlalchemy import BigInteger, Index, Integer, MetaData, String, func, select, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from tests.plugins.containers import PostgresInfo

pytestmark = pytest.mark.integration

SCHEMA = "spike_geo"
# Нови-Сад: Лиман и центр (lon, lat)
LIMAN = (19.8395, 45.2445)
CENTER = (19.8451, 45.2551)
PETROVARADIN = (19.8660, 45.2522)


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class Place(Base):
    __tablename__ = "places"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    location: Mapped[object] = mapped_column(Geography("POINT", srid=4326, spatial_index=False))
    attrs: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    category_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)

    __table_args__ = (
        Index("ix_places_location", "location", postgresql_using="gist"),
        Index("ix_places_category_ids", "category_ids", postgresql_using="gin"),
    )


class District(Base):
    __tablename__ = "districts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    area: Mapped[object] = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=False))

    __table_args__ = (Index("ix_districts_area", "area", postgresql_using="gist"),)


def _point(lon_lat: tuple[float, float]) -> object:
    return func.ST_GeogFromText(f"SRID=4326;POINT({lon_lat[0]} {lon_lat[1]})")


def _box(x1: float, y1: float, x2: float, y2: float) -> str:
    return f"SRID=4326;MULTIPOLYGON((({x1} {y1},{x2} {y1},{x2} {y2},{x1} {y2},{x1} {y1})))"


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def spike_schema(migrator_engine: AsyncEngine) -> AsyncIterator[None]:
    async with migrator_engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with migrator_engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA {SCHEMA} CASCADE"))


@pytest_asyncio.fixture(loop_scope="session")
async def session(spike_schema: None, postgres: PostgresInfo) -> AsyncIterator[AsyncSession]:
    """Собственный engine теста под ролью app, как требует план спайка."""
    engine = sqlalchemy.ext.asyncio.create_async_engine(postgres.dsn("app"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        s.add_all(
            [
                Place(
                    id=1,
                    name="Лиман",
                    location=_point(LIMAN),
                    attrs={"lang": ["ru", "sr"]},
                    category_ids=[1, 5],
                ),
                Place(
                    id=2,
                    name="Центр",
                    location=_point(CENTER),
                    attrs={"lang": ["sr"]},
                    category_ids=[2],
                ),
                Place(
                    id=3,
                    name="Петроварадин",
                    location=_point(PETROVARADIN),
                    attrs={},
                    category_ids=[1],
                ),
                District(
                    id=1, name="Лиман", area=func.ST_GeomFromEWKT(_box(19.83, 45.235, 19.85, 45.25))
                ),
            ]
        )
        await s.commit()
        yield s
        await s.execute(text(f"DELETE FROM {SCHEMA}.places"))
        await s.execute(text(f"DELETE FROM {SCHEMA}.districts"))
        await s.commit()
    await engine.dispose()


async def test_no_duplicate_spatial_indexes(session: AsyncSession) -> None:
    """GeoAlchemy2 по умолчанию создаёт свой GiST-индекс idx_<table>_<column>. С явным
    индексом по нашему naming convention получится дубль — поэтому spatial_index=False."""
    rows = await session.execute(
        text("SELECT indexname FROM pg_indexes WHERE schemaname = :s ORDER BY indexname"),
        {"s": SCHEMA},
    )
    assert [r[0] for r in rows] == [
        "districts_pkey",
        "ix_districts_area",
        "ix_places_category_ids",
        "ix_places_location",
        "places_pkey",
    ]


def test_versions_under_test() -> None:
    assert sqlalchemy.__version__.startswith("2.1.")
    assert geoalchemy2.__version__.startswith("0.20.")


async def test_geography_dwithin_uses_meters(session: AsyncSession) -> None:
    rows = await session.scalars(
        select(Place.name).where(func.ST_DWithin(Place.location, _point(LIMAN), 1500))
    )
    assert set(rows) == {"Лиман", "Центр"}  # центр ≈ 1,2 км, Петроварадин ≈ 2,4 км


async def test_distance_in_meters(session: AsyncSession) -> None:
    meters = await session.scalar(
        select(func.ST_Distance(Place.location, _point(LIMAN))).where(Place.id == 2)
    )
    assert meters is not None
    assert 1000 < float(meters) < 1400


async def test_knn_orders_by_distance(session: AsyncSession) -> None:
    rows = await session.scalars(
        select(Place.name).order_by(Place.location.op("<->")(_point(PETROVARADIN))).limit(2)
    )
    assert list(rows) == ["Петроварадин", "Центр"]


async def test_multipolygon_covers_point(session: AsyncSession) -> None:
    name = await session.scalar(
        select(District.name).where(
            func.ST_Covers(District.area, func.ST_SetSRID(func.ST_MakePoint(*LIMAN), 4326))
        )
    )
    assert name == "Лиман"


async def test_jsonb_and_int_array(session: AsyncSession) -> None:
    by_lang = await session.scalars(select(Place.name).where(Place.attrs["lang"].contains(["ru"])))
    assert list(by_lang) == ["Лиман"]
    by_category = await session.scalars(
        select(Place.name).where(Place.category_ids.overlap([1])).order_by(Place.id)
    )
    assert list(by_category) == ["Лиман", "Петроварадин"]


async def test_orm_roundtrip_returns_geography(session: AsyncSession) -> None:
    place = await session.get(Place, 1)
    assert place is not None
    wkt = await session.scalar(select(func.ST_AsText(Place.location)).where(Place.id == 1))
    assert wkt == f"POINT({LIMAN[0]} {LIMAN[1]})"


async def test_custom_plans_after_server_side_prepare(
    session: AsyncSession, migrator_engine: AsyncEngine
) -> None:
    """psycopg готовит запрос на сервере после 5 выполнений; force_custom_plan роли app
    должен давать план под конкретные параметры и на 6-м, 7-м выполнении."""
    assert (await session.scalar(text("SHOW plan_cache_mode"))) == "force_custom_plan"
    query = text(
        f"SELECT name FROM {SCHEMA}.places "
        "WHERE ST_DWithin(location, ST_GeogFromText(:p), :r) ORDER BY name"
    )
    params = {"p": f"SRID=4326;POINT({LIMAN[0]} {LIMAN[1]})", "r": 1500}
    for _ in range(7):
        rows = (await session.execute(query, params)).scalars().all()
        assert rows == ["Лиман", "Центр"]
    # Реалистичный объём: 2000 точек вокруг Нови-Сада, статистика собрана владельцем таблицы.
    # Тогда планировщик сам выбирает GiST-индекс — без enable_seqscan=off.
    await session.execute(
        text(
            f"INSERT INTO {SCHEMA}.places (id, name, location, attrs, category_ids) "
            "SELECT 1000 + g, 'p' || g, ST_GeogFromText(format('SRID=4326;POINT(%s %s)', "
            "19.70 + (g % 50) * 0.006, 45.20 + (g / 50) * 0.003)), '{}', '{}' "
            "FROM generate_series(1, 2000) AS g"
        )
    )
    await session.commit()
    async with migrator_engine.begin() as conn:
        await conn.execute(text(f"ANALYZE {SCHEMA}.places"))
    plan = (await session.execute(text(f"EXPLAIN (FORMAT JSON) {query.text}"), params)).scalar_one()
    assert "ix_places_location" in _index_names(plan[0]["Plan"]), plan


def _index_names(node: dict[str, object]) -> set[str]:
    names = {str(node["Index Name"])} if "Index Name" in node else set()
    for child in node.get("Plans", []):  # type: ignore[union-attr]
        names |= _index_names(child)
    return names
