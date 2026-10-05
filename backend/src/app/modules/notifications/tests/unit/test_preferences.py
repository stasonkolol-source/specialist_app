"""Настройки уведомлений (S43): тихие часы по Белграду и группы × каналы (2.3a)."""

from datetime import UTC, datetime, time

import pytest

from app.modules.notifications.domain.catalog import (
    CATALOG,
    MANDATORY_GROUPS,
    Channel,
    EventGroup,
    NotificationType,
    Priority,
)
from app.modules.notifications.domain.settings import (
    TIMEZONE,
    NotificationSettings,
    Preferences,
    QuietHours,
)
from app.modules.notifications.errors import MandatoryGroupError
from app.platform.kernel.errors import DomainValidationError

pytestmark = pytest.mark.unit


def belgrade(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TIMEZONE)


@pytest.mark.parametrize(
    ("created", "released"),
    [
        (belgrade(2026, 10, 12, 23, 30), belgrade(2026, 10, 13, 8, 0)),  # вечер — утром
        (belgrade(2026, 10, 13, 3, 0), belgrade(2026, 10, 13, 8, 0)),  # ночь — в тот же день
        (belgrade(2026, 10, 12, 22, 0), belgrade(2026, 10, 13, 8, 0)),  # ровно начало — уже тихо
        (belgrade(2026, 10, 13, 8, 0), belgrade(2026, 10, 13, 8, 0)),  # ровно конец — сразу
        (belgrade(2026, 10, 13, 14, 0), belgrade(2026, 10, 13, 14, 0)),  # день — сразу
    ],
    ids=["evening", "night", "start", "end", "day"],
)
def test_quiet_hours_move_delivery_to_the_morning(created: datetime, released: datetime) -> None:
    assert QuietHours().release_at(created.astimezone(UTC)) == released


def test_morning_after_the_switch_to_winter_time_is_8_local() -> None:
    # 25.10.2026 в 03:00 Белград переходит на зимнее время: утро — 08:00 CET, 07:00 UTC
    released = QuietHours().release_at(belgrade(2026, 10, 24, 23, 0).astimezone(UTC))

    assert released == datetime(2026, 10, 25, 7, 0, tzinfo=UTC)


@pytest.mark.parametrize("start", [time(22, 0), time(1, 0)], ids=["overnight", "same-day"])
@pytest.mark.parametrize("hour", [0, 1], ids=["first-02", "second-02"])
@pytest.mark.parametrize(("minute", "release_minute"), [(15, 45), (45, 45), (50, 50)])
def test_quiet_hours_respect_the_repeated_hour(
    start: time, hour: int, minute: int, release_minute: int
) -> None:
    # 02:00–03:00 повторяется: конец окна 02:45 должен относиться к текущему повторению.
    quiet = QuietHours(start=start, end=time(2, 45))
    created = datetime(2026, 10, 25, hour, minute, tzinfo=UTC)

    assert quiet.release_at(created) == datetime(2026, 10, 25, hour, release_minute, tzinfo=UTC)


def test_window_inside_the_day_and_disabled_hours() -> None:
    siesta = QuietHours(start=time(13, 0), end=time(15, 0))
    assert siesta.release_at(belgrade(2026, 10, 13, 14, 0)) == belgrade(2026, 10, 13, 15, 0)
    assert siesta.release_at(belgrade(2026, 10, 13, 23, 0)) == belgrade(2026, 10, 13, 23, 0)

    night = belgrade(2026, 10, 13, 2, 0)
    assert QuietHours(enabled=False).release_at(night) == night


def test_empty_window_is_invalid() -> None:
    with pytest.raises(DomainValidationError):
        QuietHours(start=time(8, 0), end=time(8, 0))


def test_everything_is_on_by_default_except_opt_in_groups() -> None:
    preferences = Preferences()
    # новости и запуск «Вещей» — только по согласию: кнопка S58 или отметка S43
    opt_in = {EventGroup.MARKETING, EventGroup.GOODS_LAUNCH}

    for group in EventGroup:
        for channel in Channel:
            assert preferences.allows(group, channel) is (group not in opt_in)


def test_service_notifications_cannot_be_turned_off() -> None:
    with pytest.raises(MandatoryGroupError):
        Preferences({(EventGroup.ACCOUNT, Channel.TELEGRAM): False})
    # включить — можно (это и так умолчание)
    assert Preferences({(EventGroup.ACCOUNT, Channel.IN_APP): True}).allows(
        EventGroup.ACCOUNT, Channel.IN_APP
    )


def test_only_changes_from_defaults_are_stored() -> None:
    preferences = Preferences(
        {
            (EventGroup.JOB_MATCHES, Channel.TELEGRAM): False,  # изменено
            (EventGroup.MESSAGES, Channel.TELEGRAM): True,  # как по умолчанию
            (EventGroup.MARKETING, Channel.IN_APP): True,  # opt-in
            (EventGroup.ACCOUNT, Channel.TELEGRAM): True,  # служебная
        }
    )

    assert preferences.overrides() == {
        (EventGroup.JOB_MATCHES, Channel.TELEGRAM): False,
        (EventGroup.MARKETING, Channel.IN_APP): True,
    }


def test_digest_hour_is_an_hour_of_the_day() -> None:
    with pytest.raises(DomainValidationError):
        NotificationSettings(digest_hour=24)


def test_catalog_follows_the_architecture() -> None:
    assert set(CATALOG) == set(NotificationType)
    # в тихие часы — только сообщения, выбор исполнителя и договорённость (§11.2)
    assert {t for t, spec in CATALOG.items() if spec.quiet_exempt} == {
        NotificationType.MESSAGE_RECEIVED,
        NotificationType.RESPONSE_ACCEPTED,
        NotificationType.DEAL_PROPOSED,
        NotificationType.SYSTEM_TEST,  # проверку канала человек ждёт сейчас
    }
    assert {t for t, spec in CATALOG.items() if spec.group in MANDATORY_GROUPS} == {
        NotificationType.MODERATION_DECISION,
        NotificationType.PROFILE_PUBLISHED,  # тоже решение модерации
        NotificationType.JOB_PUBLISHED,  # и это: заявку опубликовал модератор
        NotificationType.ACCOUNT_RESTRICTED,
        NotificationType.DISPUTE_RESOLVED,  # решение по спору — statement of reasons (6.1c)
        NotificationType.SYSTEM_TEST,
    }
    # исходы для исполнителя — только в центре S42, в бот не пишем (UX-аудит №11)
    assert {t for t, spec in CATALOG.items() if Channel.TELEGRAM not in spec.channels} == {
        NotificationType.RESPONSE_DECLINED,
        NotificationType.DEAL_COMPLETED,
    }


def test_urgent_types_are_taken_from_the_queue_first() -> None:
    # P0 — первым; рассылки (P4) — ниже задач-подписчиков с приоритетом по умолчанию 0 (2.7b)
    assert [p.job_priority for p in Priority] == [3, 2, 1, 0, -1]
