"""Ядро: базовые типы домена (DEVELOPMENT_PLAN 0.7a, ADR-0020 §2)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.platform.kernel.aggregate import (
    AggregateRoot,
    StatusChange,
    VersionedAggregate,
    aggregate_state,
)
from app.platform.kernel.clock import SystemClock, ensure_utc
from app.platform.kernel.errors import (
    ConcurrentModificationError,
    ConflictError,
    DomainError,
    DomainValidationError,
    RestrictedError,
    StaleVersionError,
)
from app.platform.kernel.events import DomainEvent
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import UserId, new_id
from app.platform.kernel.localized import Locale, LocalizedText
from app.platform.kernel.money import Currency, CurrencyMismatchError, Money
from app.platform.kernel.pagination import MAX_LIMIT, Page, PageRequest
from app.platform.kernel.principal import Principal, Role
from app.platform.testing.assertions import assert_same_state
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


# --- Money -------------------------------------------------------------------------------


def test_money_arithmetic_and_comparison() -> None:
    price = Money.rsd(5000)
    assert price.amount == 500_000
    assert price.major == 5000
    assert price + Money.rsd(1000) == Money.rsd(6000)
    assert price - Money.rsd(1500) == Money.rsd(3500)
    assert price * 2 == Money.rsd(10_000)
    assert 3 * Money.rsd(1) == Money.rsd(3)
    assert Money.rsd(3500) < price <= Money.rsd(5000)
    assert max(Money.rsd(2000), Money.rsd(4000)) == Money.rsd(4000)
    assert (Money.rsd(1) - Money.rsd(2)).is_negative()


def test_money_rejects_mixing_currencies() -> None:
    stars = Money(100, Currency.XTR)
    with pytest.raises(CurrencyMismatchError):
        _ = Money.rsd(1) + stars
    with pytest.raises(CurrencyMismatchError):
        _ = Money.rsd(1) < stars


@pytest.mark.parametrize("bad", [1.5, True, "100"])
def test_money_amount_must_be_int_minor_units(bad: object) -> None:
    with pytest.raises(TypeError):
        Money(bad)  # type: ignore[arg-type]


def test_money_multiplies_only_by_int() -> None:
    with pytest.raises(TypeError):
        _ = Money.rsd(10) * 1.5  # type: ignore[operator]


def test_money_is_hashable_value_object() -> None:
    assert len({Money.rsd(5), Money.rsd(5), Money(500)}) == 1


# --- IDs and clock -----------------------------------------------------------------------


def test_new_id_is_uuid7_and_monotonic() -> None:
    ids = [new_id() for _ in range(10_000)]
    assert all(isinstance(i, UUID) and i.version == 7 for i in ids)
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_system_clock_is_utc_aware() -> None:
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_ensure_utc_rejects_naive() -> None:
    with pytest.raises(ValueError, match="naive"):
        ensure_utc(datetime(2026, 1, 1))  # noqa: DTZ001
    assert ensure_utc(NOW) == NOW


def test_fake_clock_advances() -> None:
    clock = FakeClock(NOW)
    assert clock.now() == NOW
    assert clock.advance(timedelta(hours=2)) == NOW + timedelta(hours=2)
    with pytest.raises(ValueError, match="aware"):
        FakeClock(datetime(2026, 1, 1))  # noqa: DTZ001


# --- LocalizedText -----------------------------------------------------------------------


def test_localized_text_exact_and_fallbacks() -> None:
    text = LocalizedText({Locale.RU: "Электрик", Locale.SR_LATN: "Električar"})
    assert text.get(Locale.RU) == "Электрик"
    assert text.get(Locale.SR_CYRL) == "Električar"  # сербская кириллица → латиница
    assert text.get(Locale.EN) == "Электрик"


def test_localized_text_serbian_variants_fall_back_to_each_other() -> None:
    cyr = LocalizedText({Locale.SR_CYRL: "Електричар"})
    assert cyr.get(Locale.SR_LATN) == "Електричар"
    assert cyr.get(Locale.RU) == "Електричар"


def test_localized_text_validation() -> None:
    with pytest.raises(DomainValidationError):
        LocalizedText({Locale.RU: "   "})
    with pytest.raises(DomainValidationError):
        LocalizedText.from_mapping({"de": "Elektriker"})
    assert LocalizedText.from_mapping({"ru": " Уборка "}).to_mapping() == {"ru": "Уборка"}


# --- GeoPoint, pagination, principal -----------------------------------------------------


def test_geo_point_validation_and_ewkt() -> None:
    liman = GeoPoint(lat=45.2445, lon=19.8395)
    assert liman.to_ewkt() == "SRID=4326;POINT(19.8395 45.2445)"
    for lat, lon in [(91, 0), (0, 181), (float("nan"), 0)]:
        with pytest.raises(DomainValidationError):
            GeoPoint(lat=lat, lon=lon)


def test_page_request_limits() -> None:
    assert PageRequest().limit == 20
    with pytest.raises(DomainValidationError):
        PageRequest(limit=0)
    with pytest.raises(DomainValidationError):
        PageRequest(limit=MAX_LIMIT + 1)
    assert Page(items=(1, 2), next_cursor="c").has_more
    assert not Page[int](items=()).has_more


def test_principal_roles() -> None:
    user = Principal(user_id=UserId(new_id()))
    assert not user.is_staff
    assert not user.has_role(Role.MODERATOR)
    admin = Principal(user_id=UserId(new_id()), roles=frozenset({Role.ADMIN}))
    assert admin.has_role(Role.MODERATOR)


# --- errors ------------------------------------------------------------------------------


class JobNotOpenError(ConflictError):
    code = "job_not_open"


def test_errors_have_stable_codes_and_params() -> None:
    err = JobNotOpenError(job_id="j1", status="closed")
    assert err.code == "job_not_open"
    assert err.params == {"job_id": "j1", "status": "closed"}
    assert isinstance(err, DomainError)
    assert "job_not_open" in str(err)
    assert issubclass(ConcurrentModificationError, ConflictError)
    assert RestrictedError.code == "restricted"
    stale = StaleVersionError(expected=3, actual=4)
    assert (stale.expected, stale.actual) == (3, 4)


# --- aggregates --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ThingRenamed(DomainEvent):
    event_type = "tests.ThingRenamed"
    name: str


@dataclass(eq=False, kw_only=True)
class Thing(VersionedAggregate):
    id: UUID
    name: str
    tags: list[str] = field(default_factory=list)
    _cache: str = field(default="", init=False, repr=False)

    def rename(self, name: str, *, now: datetime) -> None:
        self.name = name
        self._cache = name
        self._record(ThingRenamed(name=name, occurred_at=now))


def test_aggregate_records_and_pulls_events() -> None:
    thing = Thing(id=new_id(), name="a", version=1)
    thing.rename("b", now=NOW)
    events = thing.pull_events()
    assert [type(e) for e in events] == [ThingRenamed]
    assert events[0].name == "b"  # type: ignore[attr-defined]
    assert events[0].event_id.version == 7
    assert thing.pull_events() == []


def test_ensure_version() -> None:
    thing = Thing(id=new_id(), name="a", version=3)
    thing.ensure_version(None)
    thing.ensure_version(3)
    with pytest.raises(StaleVersionError):
        thing.ensure_version(2)
    thing.mark_persisted(version=4)
    assert thing.version == 4


def test_aggregate_state_ignores_private_fields_and_copies() -> None:
    thing = Thing(id=new_id(), name="a", version=1, tags=["x"])
    thing.rename("b", now=NOW)
    state = aggregate_state(thing)
    assert set(state) == {"id", "name", "tags", "version"}
    thing.tags.append("y")
    assert state["tags"] == ["x"]  # снимок — копия


def test_aggregates_compare_by_identity_and_state_helper() -> None:
    same_id = new_id()
    a = Thing(id=same_id, name="a", version=1)
    b = Thing(id=same_id, name="a", version=1)
    assert a != b
    assert_same_state(a, b)
    b.rename("c", now=NOW)
    with pytest.raises(AssertionError, match="name"):
        assert_same_state(a, b)


def test_status_change_record() -> None:
    change = StatusChange(from_="draft", to="published", actor_id=None, reason=None, at=NOW)
    assert change.to == "published"


def test_aggregate_root_without_version() -> None:
    @dataclass(eq=False, kw_only=True)
    class Note(AggregateRoot):
        text: str

    assert aggregate_state(Note(text="t")) == {"text": "t"}
