"""Основа БД и репозиториев на настоящем PostgreSQL (DEVELOPMENT_PLAN 0.7b, ADR-0020 §5)."""

from collections.abc import Callable

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.platform.kernel.errors import ConcurrentModificationError
from app.platform.kernel.ids import UserId, new_id
from app.platform.kernel.localized import Locale
from app.platform.kernel.money import Money
from app.platform.kernel.pagination import PageRequest
from app.platform.testing.assertions import assert_same_state
from tests.integration.db.conftest import LIMAN, NOW, Scope, make_widget
from tests.integration.db.sample import (
    SCHEMA,
    DuplicateWidgetTitleError,
    SqlWidgetQuery,
    WidgetNotFoundError,
    WidgetRow,
    WidgetStatus,
)

pytestmark = pytest.mark.integration

Maker = async_sessionmaker[AsyncSession]
Build = Callable[[AsyncSession], Scope]


async def test_server_default_uuid7_is_monotonic(maker: Maker) -> None:
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


async def test_roundtrip_add_then_get_keeps_state(maker: Maker, scope_factory: Build) -> None:
    widget = make_widget(UserId(new_id()))
    widget.add_part("крюк")
    widget.add_part("клеммы")
    async with maker() as s:
        sc = scope_factory(s)
        async with sc.uow:
            await sc.repo.add(widget)
    async with maker() as s:
        sc = scope_factory(s)
        async with sc.uow:
            loaded = await sc.repo.get(widget.id)
    assert_same_state(widget, loaded)
    assert loaded.location == LIMAN
    assert loaded.name.get(Locale.SR_CYRL) == "Luster"


async def test_save_bumps_version_writes_history_and_children(
    maker: Maker, scope_factory: Build
) -> None:
    widget = make_widget(UserId(new_id()))
    async with maker() as s:
        sc = scope_factory(s)
        async with sc.uow:
            await sc.repo.add(widget)
    async with maker() as s:
        sc = scope_factory(s)
        async with sc.uow:
            loaded = await sc.repo.get(widget.id)
            loaded.publish(by=loaded.owner_id, now=NOW)
            loaded.add_part("стремянка")  # меняется подагрегат — версия корня всё равно растёт
            await sc.repo.save(loaded)
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
        sc = scope_factory(s)
        async with sc.uow:
            again = await sc.repo.get(widget.id)
    assert again.status is WidgetStatus.PUBLISHED
    assert again.parts == ["стремянка"]
    assert again.version == 2


async def test_concurrent_edit_is_409_caused_by_stale_data_on_flush(
    maker: Maker, scope_factory: Build
) -> None:
    widget = make_widget(UserId(new_id()))
    async with maker() as s:
        sc = scope_factory(s)
        async with sc.uow:
            await sc.repo.add(widget)
    async with maker() as first, maker() as second:
        a_sc, b_sc = scope_factory(first), scope_factory(second)
        with pytest.raises(ConcurrentModificationError) as info:
            async with b_sc.uow:
                b = await b_sc.repo.get(widget.id)  # b прочитал версию 1
                async with a_sc.uow:  # тем временем a правит и фиксирует версию 2
                    a = await a_sc.repo.get(widget.id)
                    a.add_part("a")
                    await a_sc.repo.save(a)
                b.add_part("b")
                await b_sc.repo.save(b)
        assert isinstance(info.value.__cause__, StaleDataError)
    async with maker() as s:
        sc = scope_factory(s)
        async with sc.uow:
            assert (await sc.repo.get(widget.id)).parts == ["a"]  # правка b не прошла


async def test_unique_violation_is_translated_by_constraint_name(
    maker: Maker, scope_factory: Build
) -> None:
    owner = UserId(new_id())
    async with maker() as s:
        sc = scope_factory(s)
        with pytest.raises(DuplicateWidgetTitleError):
            async with sc.uow:
                await sc.repo.add(make_widget(owner, "Люстра"))
                await sc.repo.add(make_widget(owner, "Люстра"))


async def test_soft_delete_hides_row_and_frees_partial_unique(
    maker: Maker, scope_factory: Build
) -> None:
    owner = UserId(new_id())
    first = make_widget(owner, "Шкаф")
    async with maker() as s:
        sc = scope_factory(s)
        async with sc.uow:
            await sc.repo.add(first)
            loaded = await sc.repo.get(first.id)
            loaded.delete(now=NOW)
            await sc.repo.save(loaded)
            await sc.repo.add(make_widget(owner, "Шкаф"))  # частичный unique: удалённый не мешает
    async with maker() as s:
        sc = scope_factory(s)
        with pytest.raises(WidgetNotFoundError):
            async with sc.uow:
                await sc.repo.get(first.id)


async def test_lazy_relationship_access_raises(maker: Maker, scope_factory: Build) -> None:
    widget = make_widget(UserId(new_id()))
    async with maker() as s:
        sc = scope_factory(s)
        async with sc.uow:
            await sc.repo.add(widget)
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


async def test_database_checks_guard_invariants(maker: Maker) -> None:
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
    maker: Maker, scope_factory: Build
) -> None:
    owner = UserId(new_id())
    async with maker() as s:
        sc = scope_factory(s)
        async with sc.uow:
            for i in range(5):
                await sc.repo.add(make_widget(owner, f"w{i}"))
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
