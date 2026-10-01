"""Профиль исполнителя (DEVELOPMENT_PLAN 2.8a): жизненный цикл, поля, чего не хватает."""

from datetime import UTC, datetime, time, timedelta

import pytest

from app.modules.specialists.domain.profile import (
    Language,
    Profile,
    ProfileKind,
    ProfileStatus,
    WorkMode,
    today_at,
)
from app.modules.specialists.errors import (
    AvailabilityPastError,
    InvalidProfileError,
    ProfileIncompleteError,
    ProfileStateError,
)
from app.platform.contracts.events.specialists import (
    AvailabilityChanged,
    ProfileHidden,
    ProfilePublished,
    ProfileSubmitted,
    ProfileUpdated,
)
from app.platform.kernel.ids import CategoryId, CityId, DistrictId, UserId, new_id

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
CATEGORY, DISTRICT = CategoryId(57), DistrictId(3)


def draft(kind: ProfileKind = ProfileKind.PRO) -> Profile:
    return Profile.create(
        user_id=UserId(new_id()),
        kind=kind,
        display_name=" Ana  Petrović ",
        city_id=CityId(1),
        now=NOW,
    )


def ready(kind: ProfileKind = ProfileKind.PRO) -> Profile:
    profile = draft(kind)
    profile.edit(now=NOW, headline="Электрик, 10 лет опыта", work_modes=["at_client"])
    profile.set_categories([CATEGORY], now=NOW)
    profile.set_areas([DISTRICT], base=None, public=None, now=NOW)
    return profile


def test_new_profile_is_a_draft_and_casual_is_not_in_the_catalog() -> None:
    pro, casual = draft(), draft(ProfileKind.CASUAL)

    assert (pro.status, pro.display_name, pro.listed_in_catalog) == (
        ProfileStatus.DRAFT,
        "Ana Petrović",
        True,
    )
    assert not casual.listed_in_catalog
    assert pro.missing() == ("category_ids", "headline", "work_modes")


def test_travelling_specialist_needs_districts() -> None:
    profile = draft()
    profile.edit(now=NOW, headline="Электрик", work_modes=["at_client", "at_own_place"])
    profile.set_categories([CATEGORY], now=NOW)

    assert profile.missing() == ("area_ids",)
    profile.edit(now=NOW, work_modes=["at_own_place"])
    assert profile.missing() == ()


def test_submit_review_and_publish() -> None:
    profile = ready()
    with pytest.raises(ProfileIncompleteError) as incomplete:
        draft().submit(now=NOW)
    assert incomplete.value.params == {"missing": ["category_ids", "headline", "work_modes"]}

    profile.submit(now=NOW)
    assert profile.status is ProfileStatus.PENDING_REVIEW
    assert profile.first_review
    assert not profile.approve(now=NOW, version=profile.version + 1)  # другая версия — ничего
    assert profile.approve(now=NOW, version=profile.version)

    assert (profile.status, profile.published_at) == (ProfileStatus.PUBLISHED, NOW)
    submitted, published = profile.pull_events()
    assert isinstance(submitted, ProfileSubmitted)
    assert isinstance(published, ProfilePublished)
    assert published.approved


def test_rejection_sends_back_for_fixes_or_suspends_the_published() -> None:
    pending, published = ready(), ready()
    pending.submit(now=NOW)
    published.submit(now=NOW)
    published.approve(now=NOW)
    published.pull_events()

    pending.reject(reason_code="contact_leak", now=NOW)
    published.reject(reason_code="prohibited", now=NOW)

    assert (pending.status, pending.rejection_reason) == (ProfileStatus.DRAFT, "contact_leak")
    assert published.status is ProfileStatus.SUSPENDED
    [hidden] = published.pull_events()
    assert isinstance(hidden, ProfileHidden)
    assert hidden.by_moderation
    pending.submit(now=NOW)  # исправил и отправил снова
    assert pending.rejection_reason is None
    with pytest.raises(ProfileStateError):
        published.edit(now=NOW, headline="снова")


def test_owner_hides_and_shows_the_published_profile() -> None:
    profile = ready()
    with pytest.raises(ProfileStateError):
        profile.hide(now=NOW)
    profile.submit(now=NOW)
    profile.approve(now=NOW)
    profile.pull_events()

    profile.hide(now=NOW)
    profile.hide(now=NOW)  # повтор ничего не меняет
    profile.show(now=NOW)

    hidden, shown = profile.pull_events()
    assert isinstance(hidden, ProfileHidden)
    assert isinstance(shown, ProfilePublished)
    assert not shown.approved  # вернул владелец — уведомлять не о чем


def test_casual_becoming_pro_is_reviewed_again() -> None:
    profile = ready(ProfileKind.CASUAL)
    profile.submit(now=NOW)
    profile.approve(now=NOW)
    profile.pull_events()

    profile.become_pro(now=NOW)

    assert (profile.kind, profile.status, profile.listed_in_catalog) == (
        ProfileKind.PRO,
        ProfileStatus.PENDING_REVIEW,
        True,
    )
    assert profile.reviewed_kind
    assert [type(e) for e in profile.pull_events()] == [ProfileHidden, ProfileSubmitted]


def test_draft_changes_kind_but_a_reviewed_profile_does_not() -> None:
    profile = draft()

    assert profile.change_kind(ProfileKind.CASUAL)
    assert (profile.kind, profile.listed_in_catalog) == (ProfileKind.CASUAL, False)
    assert not profile.change_kind(ProfileKind.CASUAL)
    assert profile.pull_events() == []

    reviewed = ready(ProfileKind.CASUAL)
    reviewed.submit(now=NOW)
    with pytest.raises(ProfileStateError):
        reviewed.change_kind(ProfileKind.PRO)  # только become_pro — с повторной проверкой


def test_published_edits_are_events_for_post_moderation() -> None:
    profile = ready()
    profile.submit(now=NOW)
    profile.approve(now=NOW)
    profile.pull_events()

    changed = profile.edit(now=NOW, about="Работаю по выходным", languages=["ru", "sr", "ru"])

    assert changed == ("about", "languages")
    assert profile.languages == (Language.RU, Language.SR)
    [updated] = profile.pull_events()
    assert isinstance(updated, ProfileUpdated)
    assert updated.fields == ("about", "languages")


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"headline": "x" * 81}, "headline"),
        ({"about": "x" * 4001}, "about"),
        ({"display_name": "   "}, "display_name"),
        ({"travel_radius_km": 7}, "travel_radius_km"),
        ({"work_modes": ["teleport"]}, "work_modes"),
        ({"languages": "ru"}, "languages"),
        ({"slug": "ana"}, "slug"),
    ],
)
def test_invalid_fields_are_refused(changes: dict[str, object], field: str) -> None:
    with pytest.raises(InvalidProfileError) as invalid:
        draft().edit(now=NOW, **changes)
    assert invalid.value.params == {"field": field}


def headline(profile: Profile) -> str | None:
    return profile.headline  # без сужения типа mypy между правками


def test_category_and_text_limits() -> None:
    profile = draft()
    with pytest.raises(InvalidProfileError):
        profile.set_categories([], now=NOW)
    with pytest.raises(InvalidProfileError):
        profile.set_categories([CategoryId(i) for i in range(1, 7)], now=NOW)
    disguised = f"Мастер{chr(0x202E)} {chr(0)}на час"  # bidi-override и управляющий — прочь
    profile.edit(now=NOW, headline=disguised)
    assert headline(profile) == "Мастер на час"
    profile.edit(now=NOW, headline="")
    assert headline(profile) is None
    assert profile.edit(now=NOW, work_modes=[WorkMode.REMOTE]) == ("work_modes",)
    assert profile.work_modes == (WorkMode.REMOTE,)


def available(profile: Profile) -> datetime | None:
    """Срок «доступен сегодня» — функцией: mypy не сужает тип атрибута между вызовами."""
    return profile.available_until


def test_available_today_until_a_time_and_off() -> None:
    profile = ready()
    profile.submit(now=NOW)
    profile.approve(now=NOW)
    profile.pull_events()

    # NOW — 12:00 по Белграду (10:00 UTC): «до 20:00» — сегодня в 18:00 UTC
    assert profile.set_availability(time(20), now=NOW)
    assert profile.available_until == datetime(2026, 10, 1, 18, 0, tzinfo=UTC)
    assert not profile.set_availability(time(20), now=NOW)  # то же — без события
    assert profile.set_availability(None, now=NOW)
    assert available(profile) is None
    events = profile.pull_events()
    assert [type(e) for e in events] == [AvailabilityChanged, AvailabilityChanged]
    off = events[1]
    assert isinstance(off, AvailabilityChanged)
    assert off.available_until is None

    with pytest.raises(AvailabilityPastError):
        profile.set_availability(time(11, 59), now=NOW)


def test_expired_availability_is_switched_off() -> None:
    profile = ready()
    profile.set_availability(time(18), now=NOW)
    profile.pull_events()

    assert not profile.expire_availability(now=NOW)  # ещё не вышло
    later = NOW + timedelta(hours=8)
    assert profile.expire_availability(now=later)
    assert available(profile) is None
    assert [type(e) for e in profile.pull_events()] == [AvailabilityChanged]


def test_today_is_the_business_day_in_belgrade() -> None:
    # 23:30 UTC 1 октября — уже 2 октября в Белграде (UTC+2)
    late = datetime(2026, 10, 1, 23, 30, tzinfo=UTC)
    assert today_at(time(20), now=late) == datetime(2026, 10, 2, 18, 0, tzinfo=UTC)
