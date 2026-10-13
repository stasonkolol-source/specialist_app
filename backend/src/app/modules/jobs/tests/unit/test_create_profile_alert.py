"""Подписка из профиля (`jobs.create_profile_alert`, DEVELOPMENT_PLAN 5.7): при первой публикации
профиля — подписка «сразу» по его категориям и районам, все районы города — весь город; у кого
подписки уже есть, профиль скрыт или категории выключены — ничего; повтор не дублирует."""

from collections.abc import Collection
from datetime import UTC, datetime
from typing import Self, cast
from uuid import UUID

import pytest

from app.modules.catalog.api import CatalogApi, CategorySummary, RiskLevel
from app.modules.geo.api import GeoApi
from app.modules.jobs.application.ports import JobAlerts
from app.modules.jobs.application.use_cases.create_profile_alert import (
    CreateProfileAlert,
    CreateProfileAlertCommand,
)
from app.modules.jobs.domain.alert import AlertDelivery, JobAlert
from app.modules.specialists.api import PublicProfile, SpecialistsApi
from app.platform.contracts.events.jobs import AlertCreated
from app.platform.db.port import UnitOfWork
from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, UserId, new_id
from app.platform.kernel.localized import Locale, LocalizedText
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)
ANA = UserId(new_id())
PROFILE = new_id()
CITY = CityId(1)
ELECTRICAL, PLUMBING, STOPPED = CategoryId(5), CategoryId(6), CategoryId(7)
LIMAN, GRBAVICA = DistrictId(11), DistrictId(12)


def profile(
    *,
    user_id: UserId = ANA,
    kind: str = "pro",
    categories: tuple[CategoryId, ...] = (ELECTRICAL, PLUMBING),
    areas: tuple[DistrictId, ...] = (LIMAN, GRBAVICA),
) -> PublicProfile:
    return PublicProfile(
        id=PROFILE,
        user_id=user_id,
        kind=kind,
        display_name="Ana",
        headline=None,
        about=None,
        languages=("ru",),
        city_id=CITY,
        area_ids=areas,
        travel_radius_km=None,
        work_modes=("at_client",),
        category_ids=categories,
        available_until=None,
        avatar_media_id=None,
        is_founding=False,
        published_at=NOW,
        works=(),
    )


def category(
    category_id: CategoryId, *, active: bool = True, forbidden: bool = False
) -> CategorySummary:
    return CategorySummary(
        id=category_id,
        parent_id=None,
        slug=f"c{category_id}",
        name=LocalizedText({Locale.RU: f"Категория {category_id}"}),
        path=(category_id,),
        risk_level=RiskLevel.FORBIDDEN if forbidden else RiskLevel.NORMAL,
        is_active=active,
        jobs_enabled=True,
        max_responses=5,
    )


class Transactions:
    def __init__(self) -> None:
        self.opened = 0
        self.events: list[DomainEvent] = []

    async def __aenter__(self) -> Self:
        self.opened += 1
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def add_event(self, event: DomainEvent) -> None:
        self.events.append(event)


class Alerts:
    def __init__(self, existing: list[JobAlert] | None = None) -> None:
        self.alerts = list(existing or [])
        self.locked: list[UserId] = []

    async def lock(self, user_id: UserId) -> None:
        self.locked.append(user_id)

    async def of_user(self, user_id: UserId) -> list[JobAlert]:
        return [alert for alert in self.alerts if alert.user_id == user_id]

    async def add(self, alert: JobAlert) -> None:
        self.alerts.append(alert)


class Specialists:
    def __init__(self, found: PublicProfile | None) -> None:
        self.found = found

    async def public_profile(self, profile_id: UUID) -> PublicProfile | None:
        return self.found if self.found is not None and self.found.id == profile_id else None


class Catalog:
    def __init__(self, known: list[CategorySummary]) -> None:
        self.known = known

    async def categories(self, category_ids: Collection[CategoryId]) -> list[CategorySummary]:
        return [item for item in self.known if item.id in category_ids]


class Geo:
    def __init__(self, *, whole_city: bool = False) -> None:
        self.whole_city = whole_city
        self.asked: list[tuple[CityId, tuple[DistrictId, ...]]] = []

    async def covers_city(self, city_id: CityId, district_ids: Collection[DistrictId]) -> bool:
        self.asked.append((city_id, tuple(district_ids)))
        return self.whole_city


def use_case(
    found: PublicProfile | None,
    *,
    alerts: Alerts | None = None,
    known: list[CategorySummary] | None = None,
    geo: Geo | None = None,
) -> tuple[CreateProfileAlert, Transactions, Alerts]:
    uow, store = Transactions(), alerts or Alerts()
    create = CreateProfileAlert(
        cast(UnitOfWork, uow),
        cast(JobAlerts, store),
        cast(SpecialistsApi, Specialists(found)),
        cast(CatalogApi, Catalog(known or [category(ELECTRICAL), category(PLUMBING)])),
        cast(GeoApi, geo or Geo()),
        FakeClock(NOW),
    )
    return create, uow, store


COMMAND = CreateProfileAlertCommand(user_id=ANA, profile_id=PROFILE)


@pytest.mark.parametrize("kind", ["pro", "casual"])
async def test_first_publication_subscribes_to_profile_categories_and_areas(kind: str) -> None:
    create, uow, alerts = use_case(profile(kind=kind))

    created = await create(COMMAND)

    assert created is not None
    assert alerts.alerts == [created]
    assert alerts.locked == [ANA]
    assert created.user_id == ANA
    assert created.criteria.category_ids == (ELECTRICAL, PLUMBING)
    assert created.criteria.city_id == CITY
    assert created.criteria.district_ids == (LIMAN, GRBAVICA)
    assert created.criteria.center is None
    assert (
        created.criteria.min_budget,
        created.criteria.urgencies,
        created.criteria.languages,
    ) == (
        None,
        (),
        (),
    )
    assert created.delivery is AlertDelivery.INSTANT
    assert created.receives(NOW)
    [event] = uow.events
    assert isinstance(event, AlertCreated)
    assert (event.alert_id, event.user_id, event.auto, event.area) == (
        created.id,
        ANA,
        True,
        "districts",
    )


async def test_all_districts_of_the_city_mean_the_whole_city() -> None:
    geo = Geo(whole_city=True)
    create, _, _ = use_case(profile(), geo=geo)

    created = await create(COMMAND)

    assert created is not None
    assert created.criteria.district_ids == ()
    assert geo.asked == [(CITY, (LIMAN, GRBAVICA))]


async def test_profile_without_areas_subscribes_to_the_whole_city_without_asking_geo() -> None:
    geo = Geo()
    create, _, _ = use_case(profile(areas=()), geo=geo)

    created = await create(COMMAND)

    assert created is not None
    assert (created.criteria.district_ids, geo.asked) == ((), [])


async def test_stopped_and_disabled_categories_are_skipped() -> None:
    known = [
        category(ELECTRICAL, active=False),
        category(PLUMBING),
        category(STOPPED, forbidden=True),
    ]
    create, _, _ = use_case(profile(categories=(ELECTRICAL, PLUMBING, STOPPED)), known=known)

    created = await create(COMMAND)

    assert created is not None
    assert created.criteria.category_ids == (PLUMBING,)


async def test_nothing_without_open_categories_or_published_profile() -> None:
    no_categories, uow, alerts = use_case(profile(), known=[category(ELECTRICAL, active=False)])
    assert await no_categories(COMMAND) is None

    hidden, _, _ = use_case(None)
    assert await hidden(COMMAND) is None

    someone_elses, _, _ = use_case(profile(user_id=UserId(new_id())))
    assert await someone_elses(COMMAND) is None

    assert (uow.opened, alerts.alerts) == (0, [])


async def test_existing_alerts_are_left_alone_and_repeat_does_not_duplicate() -> None:
    create, uow, alerts = use_case(profile())
    first = await create(COMMAND)
    assert first is not None

    again = await create(COMMAND)  # повторная публикация профиля после правок

    assert again is None
    assert alerts.alerts == [first]
    assert (uow.opened, len(uow.events)) == (1, 1)

    own = Alerts([first])
    with_own, uow, _ = use_case(profile(), alerts=own)
    assert await with_own(COMMAND) is None
    assert (uow.opened, own.locked) == (0, [])
