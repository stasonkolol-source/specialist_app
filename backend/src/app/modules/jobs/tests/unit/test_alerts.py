"""Подписки на заявки: правила условий, пауза и кому уходит заявка (DEVELOPMENT_PLAN 5.7)."""

from datetime import UTC, datetime

import pytest

from app.modules.jobs.application.alerts import (
    INSTANT_PER_DAY,
    INSTANT_PER_HOUR,
    AlertCandidate,
    RecentCards,
    route_matches,
)
from app.modules.jobs.domain.alert import (
    MAX_RADIUS_M,
    AlertCriteria,
    AlertDelivery,
    AlertId,
    PauseSpan,
    pause_end,
)
from app.modules.jobs.domain.job import Urgency
from app.modules.jobs.errors import InvalidAlertError
from app.platform.kernel.geo import GeoPoint
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, UserId, new_id

pytestmark = pytest.mark.unit

POINT = GeoPoint(lat=45.25, lon=19.84)
INSTANT, DIGEST = AlertDelivery.INSTANT, AlertDelivery.DIGEST


def criteria(**overrides: object) -> AlertCriteria:
    fields: dict[str, object] = {"category_ids": (CategoryId(1),), "city_id": CityId(1)}
    return AlertCriteria(**(fields | overrides))  # type: ignore[arg-type]


def test_whole_city_districts_or_radius() -> None:
    assert criteria().center is None
    assert criteria(district_ids=(DistrictId(3), DistrictId(3))).district_ids == (DistrictId(3),)
    assert criteria(center=POINT, radius_m=3000).radius_m == 3000


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"category_ids": ()}, "category_ids"),
        ({"category_ids": tuple(CategoryId(i) for i in range(1, 22))}, "category_ids"),
        ({"center": POINT}, "radius_m"),
        ({"radius_m": 3000}, "radius_m"),
        ({"center": POINT, "radius_m": MAX_RADIUS_M + 1}, "radius_m"),
        ({"center": POINT, "radius_m": 100}, "radius_m"),
        ({"center": POINT, "radius_m": 3000, "district_ids": (DistrictId(1),)}, "district_ids"),
        ({"min_budget": 0}, "min_budget"),
        ({"languages": ("Русский",)}, "languages"),
        ({"languages": ("ru", "sr", "en", "de", "fr", "it")}, "languages"),
    ],
)
def test_invalid_criteria(overrides: dict[str, object], field: str) -> None:
    with pytest.raises(InvalidAlertError) as caught:
        criteria(**overrides)
    assert caught.value.params["field"] == field


def test_urgency_and_language_lists_are_deduplicated() -> None:
    made = criteria(urgencies=(Urgency.ASAP, Urgency.ASAP), languages=("ru", "sr-Latn", "ru"))
    assert (made.urgencies, made.languages) == ((Urgency.ASAP,), ("ru", "sr-Latn"))


def test_pause_today_ends_at_belgrade_midnight_and_week_in_seven_days() -> None:
    late = datetime(2026, 10, 3, 21, 30, tzinfo=UTC)  # 23:30 по Белграду
    assert pause_end(late, PauseSpan.TODAY) == datetime(2026, 10, 3, 22, 0, tzinfo=UTC)
    assert pause_end(late, PauseSpan.WEEK) == datetime(2026, 10, 10, 21, 30, tzinfo=UTC)


def candidate(
    user: UserId, delivery: AlertDelivery, distance: float | None = None
) -> AlertCandidate:
    return AlertCandidate(
        alert_id=AlertId(new_id()), user_id=user, delivery=delivery, distance_m=distance
    )


def test_one_card_per_person_instant_wins_over_digest() -> None:
    ana, bob = UserId(new_id()), UserId(new_id())
    digest = candidate(ana, DIGEST)
    instant = candidate(ana, INSTANT, 1234.0)
    bobs = candidate(bob, DIGEST)

    routed = route_matches([digest, instant, bobs], excluded=(), recent={})

    assert [(m.user_id, m.alert_id, m.delivery, m.distance_m) for m in routed] == [
        (ana, instant.alert_id, INSTANT, 1200),
        (bob, bobs.alert_id, DIGEST, None),
    ]


def test_blocked_and_barred_people_get_nothing() -> None:
    ana, bob = UserId(new_id()), UserId(new_id())

    routed = route_matches(
        [candidate(ana, INSTANT), candidate(bob, INSTANT)], excluded={bob}, recent={}
    )

    assert [m.user_id for m in routed] == [ana]


@pytest.mark.parametrize(
    ("hour", "day", "delivery"),
    [
        (INSTANT_PER_HOUR - 1, INSTANT_PER_HOUR - 1, INSTANT),
        (INSTANT_PER_HOUR, INSTANT_PER_HOUR, DIGEST),
        (0, INSTANT_PER_DAY, DIGEST),
    ],
)
def test_frequency_limit_moves_cards_to_the_digest(
    hour: int, day: int, delivery: AlertDelivery
) -> None:
    ana = UserId(new_id())

    [routed] = route_matches(
        [candidate(ana, INSTANT, 40.0)],
        excluded=(),
        recent={ana: RecentCards(hour=hour, day=day)},
    )

    assert routed.delivery is delivery
    assert routed.distance_m == 100  # ближе 100 м — всё равно «≈ 100 м»
