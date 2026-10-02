"""Read-model поиска специалистов (DEVELOPMENT_PLAN 4.1): событие → отметка → пересборка.

Профиль одобряет модерация, подписчик search отмечает его, `search.flush_index` пересобирает
строку. Скрытие профиля, санкция автора и удаление аккаунта убирают строку; показ и снятие
санкции возвращают; срочная санкция ставит пересборку на свой конец. Сверка чинит рассинхрон.
Контейнер воркера, данные коммитятся: тест смотрит только на свои профили.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.entrypoints._search_cli import reindex_all
from app.entrypoints._wiring import make_worker_container
from app.modules.identity.api import RestrictionKind
from app.modules.identity.application.use_cases.process_deletions import (
    ProcessDeletions,
    ProcessDeletionsCommand,
)
from app.modules.identity.application.use_cases.request_deletion import (
    RequestDeletion,
    RequestDeletionCommand,
)
from app.modules.identity.domain.deletion import DeletionSource
from app.modules.search.application.dto import SpecialistFilters
from app.modules.search.application.ports import PendingProfiles
from app.modules.search.application.use_cases.reconcile_index import (
    ReconcileIndex,
    ReconcileIndexCommand,
)
from app.modules.search.application.use_cases.search_specialists import (
    SearchSpecialists,
    SearchSpecialistsCommand,
)
from app.modules.specialists.application.use_cases.hide_profile import (
    HideProfile,
    HideProfileCommand,
)
from app.modules.specialists.application.use_cases.show_profile import (
    ShowProfile,
    ShowProfileCommand,
)
from app.modules.specialists.domain.profile import ProfileKind
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import new_id
from app.platform.settings import Settings
from tests.plugins.search import NAME, PRICE, Specialist

pytestmark = pytest.mark.integration


@pytest.fixture
async def container(
    storage_settings: Settings, geo_seeded: None, catalog_seeded: None
) -> AsyncIterator[AsyncContainer]:
    # фото профиля в карточке — через фасад media, ему нужно хранилище
    container = make_worker_container(storage_settings)
    try:
        yield container
    finally:
        await container.close()


@pytest.fixture
async def specialist(container: AsyncContainer) -> AsyncIterator[Specialist]:
    specialist = Specialist(container)
    try:
        await specialist.publish()
        await specialist.handle("search.on_profile_published")
        yield specialist
    finally:
        await specialist.drop_jobs()


async def test_published_profile_gets_a_ready_row(specialist: Specialist) -> None:
    row = await specialist.row()

    assert row is not None
    path = await specialist.scalar(
        "SELECT path FROM catalog.categories WHERE id = :id", id=specialist.category
    )
    assert (row["kind"], row["is_listed"], row["city_id"]) == ("pro", True, specialist.city)
    assert (row["district_id"], row["district_ids"]) == (specialist.district, [specialist.district])
    assert row["category_ids"] == sorted(path)
    assert (row["price_from"], row["name_norm"]) == (PRICE, "marko petrovic")
    card = row["card"]
    assert (card["display_name"], card["price_from"], card["avatar"]) == (NAME, PRICE, None)
    assert card["district"]["id"] == specialist.district
    prices = await specialist.scalar(
        "SELECT jsonb_object_agg(category_id, price_from) FROM search.specialist_category_prices"
        " WHERE profile_id = :id",
        id=specialist.profile_id,
    )
    assert prices == {str(category): PRICE for category in path}
    # название категории и словарь на любом языке и алфавите (§9.3)
    for query in ("электрик", "električar", "elektricar", "електричар", "electrician", "розетка"):
        assert await specialist.matches(query), query
    assert not await specialist.matches("сантехник")


async def test_hidden_profile_leaves_and_shown_returns(specialist: Specialist) -> None:
    await specialist.call(HideProfile, HideProfileCommand(actor_id=specialist.user_id))
    await specialist.handle("search.on_profile_hidden")
    assert await specialist.row() is None

    await specialist.call(ShowProfile, ShowProfileCommand(actor_id=specialist.user_id))
    await specialist.handle("search.on_profile_published")
    assert await specialist.row() is not None


async def test_suspended_author_is_hidden_until_the_sanction_ends(specialist: Specialist) -> None:
    until = datetime.now(UTC) + timedelta(days=3)
    case_id = await specialist.restrict(RestrictionKind.SUSPENDED, until)
    await specialist.handle("search.on_user_restricted")

    assert await specialist.row() is None
    scheduled = await specialist.scalar(
        "SELECT scheduled_at FROM procrastinate_jobs WHERE task_name = 'search.reindex_profiles'"
        " AND status = 'todo'"
        " AND args->'payload'->'profile_ids' @> jsonb_build_array(CAST(:id AS text))",
        id=str(specialist.profile_id),
    )
    assert abs((scheduled - until).total_seconds()) < 1

    await specialist.lift(case_id)
    await specialist.handle("search.on_user_restrictions_lifted")
    assert await specialist.row() is not None


async def test_posting_block_keeps_the_profile_visible(specialist: Specialist) -> None:
    await specialist.restrict(RestrictionKind.POSTING_BLOCKED, None)
    await specialist.handle("search.on_user_restricted")

    assert await specialist.row() is not None


async def test_deleted_account_leaves_the_index(specialist: Specialist) -> None:
    await specialist.call(
        RequestDeletion,
        RequestDeletionCommand(actor_id=specialist.user_id, source=DeletionSource.TMA),
    )
    await specialist.execute(
        "UPDATE identity.deletion_requests SET execute_after = now() - interval '1 minute'"
        " WHERE user_id = :user",
        user=specialist.user_id,
    )
    await specialist.call(ProcessDeletions, ProcessDeletionsCommand())
    await specialist.handle("search.on_user_deleted")

    assert await specialist.row() is None


async def test_casual_profile_is_found_only_when_explicitly_requested(
    container: AsyncContainer,
) -> None:
    casual = Specialist(container)
    try:
        await casual.publish(ProfileKind.CASUAL)
        await casual.handle("search.on_profile_published")

        row = await casual.row()
        assert row is not None
        assert (row["kind"], row["is_listed"]) == ("casual", False)

        command = SearchSpecialistsCommand(
            filters=SpecialistFilters(city_id=casual.city, kind="casual")
        )
        found = await casual.call(SearchSpecialists, command)
        assert casual.profile_id in {card.profile_id for card in found.page.items}

        default = await casual.call(
            SearchSpecialists,
            SearchSpecialistsCommand(filters=SpecialistFilters(city_id=casual.city)),
        )
        assert casual.profile_id not in {card.profile_id for card in default.page.items}

        await casual.call(HideProfile, HideProfileCommand(actor_id=casual.user_id))
        await casual.handle("search.on_profile_hidden")
        hidden = await casual.call(SearchSpecialists, command)
        assert casual.profile_id not in {card.profile_id for card in hidden.page.items}
    finally:
        await casual.drop_jobs()


async def test_reconcile_restores_lost_rows_and_drops_strays(specialist: Specialist) -> None:
    stray = UUID(int=new_id().int)
    await specialist.execute(
        "DELETE FROM search.specialist_index WHERE profile_id = :id", id=specialist.profile_id
    )
    await specialist.execute(
        "INSERT INTO search.specialist_index (profile_id, user_id, kind, is_listed, city_id,"
        " category_ids, languages, work_modes, search_vector, card, source_updated_at)"
        " VALUES (:id, :user, 'pro', true, :city, '{}', '{}', '{}', ''::tsvector, '{}', now())",
        id=stray,
        user=specialist.user_id,
        city=specialist.city,
    )

    report = await specialist.call(ReconcileIndex, ReconcileIndexCommand(page=2))
    await specialist.flush()

    assert report.published >= 1
    assert await specialist.row() is not None
    left = await specialist.scalar(
        "SELECT count(*) FROM search.specialist_index WHERE profile_id = :id", id=stray
    )
    assert left == 0


async def test_cli_reindex_rebuilds_in_place(specialist: Specialist) -> None:
    await specialist.execute(
        "DELETE FROM search.specialist_index WHERE profile_id = :id", id=specialist.profile_id
    )

    report = await reindex_all(specialist.container)

    assert report.rebuilt >= 1
    assert await specialist.row() is not None


async def test_many_marks_are_split_into_inserts(container: AsyncContainer) -> None:
    ids = [new_id() for _ in range(2_500)]  # больше одного INSERT: предел параметров PostgreSQL
    async with container() as request:
        uow, pending = await request.get(UnitOfWork), await request.get(PendingProfiles)
        async with uow:
            assert await pending.mark(ids, occurred_at=None) == len(ids)
        engine = await request.get(AsyncEngine)
        async with engine.connect() as conn:
            marked = await conn.scalar(
                text("SELECT count(*) FROM search.pending_profiles WHERE profile_id = ANY(:ids)"),
                {"ids": ids},
            )
        async with uow:
            await pending.clear(ids)

    assert marked == len(ids)
