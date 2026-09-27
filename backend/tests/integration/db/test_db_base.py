"""Основа БД и репозиториев на настоящем PostgreSQL (DEVELOPMENT_PLAN 0.7b, ADR-0020 §5)."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import UserId, new_id
from app.platform.kernel.localized import Locale, LocalizedText
from app.platform.kernel.money import Money
from app.platform.kernel.pagination import PageRequest
from app.platform.testing.assertions import assert_same_state
from tests.integration.db.sample import (
    SCHEMA,
    Base,
    DuplicateWidgetTitleError,
    SqlWidgetQuery,
    SqlWidgetRepository,
    Widget,
    WidgetNotFoundError,
    WidgetRow,
    WidgetStatus,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
LIMAN = GeoPoint(lat=45.2445, lon=19.8395)


@pytest_asyncio.fixture(scope="module", loop_scope="session")
async def sample_schema(migrator_engine: AsyncEngine) -> AsyncIterator[None]:
    async with migrator_engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with migrator_engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA {SCHEMA} CASCADE"))


@pytest_asyncio.fixture(loop_scope="session")
async def maker(
    sample_schema: None, db_engine: AsyncEngine
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield async_sessionmaker(db_engine, expire_on_commit=False, autoflush=False)
    async with db_engine.begin() as conn:
        await conn.execute(text(f"DELETE FROM {SCHEMA}.status_history"))
        await conn.execute(text(f"DELETE FROM {SCHEMA}.widget_parts"))
        await conn.execute(text(f"DELETE FROM {SCHEMA}.widgets"))


def _widget(owner: UserId, title: str = "Люстра") -> Widget:
    return Widget.create(
        owner_id=owner,
        title=title,
        name=LocalizedText({Locale.RU: "Люстра", Locale.SR_LATN: "Luster"}),
        price=Money.rsd(5000),
        location=LIMAN,
    )


async def test_server_default_uuid7_is_monotonic(maker: async_sessionmaker[AsyncSession]) -> None:
    owner = new_id()
    async with maker() as s:
        for i in range(50):
            await s.execute(
                insert(WidgetRow).values(
                    owner_id=owner,
                    title=f"w{i:02d}",
                    name={"ru": "x"},
                    price_amount=100,
                    price_currency="RSD",
                    location=LIMAN,
                    status=WidgetStatus.DRAFT,
                    version=1,
                )
            )
        await s.commit()
        ids = (
            await s.scalars(
                select(WidgetRow.id).where(WidgetRow.owner_id == owner).order_by(WidgetRow.title)
            )
        ).all()
    assert len(ids) == 50
    assert all(i.version == 7 for i in ids)
    assert list(ids) == sorted(ids)  # порядок вставки = порядок uuidv7()


async def test_roundtrip_add_then_get_keeps_state(maker: async_sessionmaker[AsyncSession]) -> None:
    widget = _widget(UserId(new_id()))
    widget.add_part("крюк")
    widget.add_part("клеммы")
    async with maker() as s:
        await SqlWidgetRepository(s).add(widget)
        await s.commit()
    async with maker() as s:
        loaded = await SqlWidgetRepository(s).get(widget.id)
    assert_same_state(widget, loaded)
    assert loaded.location == LIMAN
    assert loaded.name.get(Locale.SR_CYRL) == "Luster"


async def test_save_bumps_version_writes_history_and_children(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    widget = _widget(UserId(new_id()))
    async with maker() as s:
        await SqlWidgetRepository(s).add(widget)
        await s.commit()
    async with maker() as s:
        repo = SqlWidgetRepository(s)
        loaded = await repo.get(widget.id)
        loaded.publish(by=loaded.owner_id, now=NOW)
        loaded.add_part("стремянка")  # меняется только подагрегат — версия корня всё равно растёт
        await repo.save(loaded)
        await s.commit()
        assert loaded.version == 2
        history = (
            await s.execute(
                text(
                    f"SELECT from_status, to_status FROM {SCHEMA}.status_history "
                    "WHERE widget_id = :w"
                ),
                {"w": widget.id},
            )
        ).all()
    assert [tuple(h) for h in history] == [("draft", "published")]
    async with maker() as s:
        again = await SqlWidgetRepository(s).get(widget.id)
    assert again.status is WidgetStatus.PUBLISHED
    assert again.parts == ["стремянка"]
    assert again.version == 2


async def test_concurrent_edit_raises_stale_data_on_flush(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    widget = _widget(UserId(new_id()))
    async with maker() as s:
        await SqlWidgetRepository(s).add(widget)
        await s.commit()
    async with maker() as first, maker() as second:
        a = await SqlWidgetRepository(first).get(widget.id)
        b = await SqlWidgetRepository(second).get(widget.id)
        a.add_part("a")
        await SqlWidgetRepository(first).save(a)
        await first.commit()
        b.add_part("b")
        with pytest.raises(StaleDataError):
            await SqlWidgetRepository(second).save(b)
        await second.rollback()


async def test_unique_violation_is_translated_by_constraint_name(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    owner = UserId(new_id())
    async with maker() as s:
        repo = SqlWidgetRepository(s)
        await repo.add(_widget(owner, "Люстра"))
        with pytest.raises(DuplicateWidgetTitleError):
            await repo.add(_widget(owner, "Люстра"))
        await s.rollback()


async def test_soft_delete_hides_row_and_frees_partial_unique(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    owner = UserId(new_id())
    first = _widget(owner, "Шкаф")
    async with maker() as s:
        repo = SqlWidgetRepository(s)
        await repo.add(first)
        loaded = await repo.get(first.id)
        loaded.delete(now=NOW)
        await repo.save(loaded)
        await repo.add(_widget(owner, "Шкаф"))  # частичный unique: удалённый не мешает
        await s.commit()
    async with maker() as s:
        with pytest.raises(WidgetNotFoundError):
            await SqlWidgetRepository(s).get(first.id)


async def test_lazy_relationship_access_raises(maker: async_sessionmaker[AsyncSession]) -> None:
    widget = _widget(UserId(new_id()))
    async with maker() as s:
        await SqlWidgetRepository(s).add(widget)
        await s.commit()
    async with maker() as s:
        row = (
            await s.execute(
                select(WidgetRow)
                .where(WidgetRow.id == widget.id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        with pytest.raises(InvalidRequestError, match="lazy='raise'"):
            _ = row.parts


async def test_database_checks_guard_invariants(maker: async_sessionmaker[AsyncSession]) -> None:
    owner = new_id()
    base = {
        "owner_id": owner,
        "title": "x",
        "price_amount": 1,
        "location": LIMAN,
        "status": WidgetStatus.DRAFT,
        "version": 1,
    }
    bad_rows = [
        {**base, "name": {"de": "Leuchte"}, "price_currency": "RSD"},  # неизвестная локаль
        {**base, "name": {"ru": "x"}, "price_currency": "EUR"},  # только RSD
    ]
    for values in bad_rows:
        async with maker() as s:
            with pytest.raises(IntegrityError, match="ck_widgets"):
                await s.execute(insert(WidgetRow).values(**values))
            await s.rollback()


async def test_query_service_keyset_pagination_and_release(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    owner = UserId(new_id())
    async with maker() as s:
        repo = SqlWidgetRepository(s)
        for i in range(5):
            await repo.add(_widget(owner, f"w{i}"))
        await s.commit()
    async with maker() as s:
        query = SqlWidgetQuery(s)
        first = await query.list_for_owner(owner, PageRequest(limit=2))
        assert not s.in_transaction()  # вне UoW соединение сразу вернулось в пул
        second = await query.list_for_owner(owner, PageRequest(limit=2, cursor=first.next_cursor))
        third = await query.list_for_owner(owner, PageRequest(limit=2, cursor=second.next_cursor))
    titles = [i.title for page in (first, second, third) for i in page.items]
    assert sorted(titles) == ["w0", "w1", "w2", "w3", "w4"]
    assert len(set(titles)) == 5
    assert third.next_cursor is None
    assert all(i.price == Money.rsd(5000) for i in first.items)
