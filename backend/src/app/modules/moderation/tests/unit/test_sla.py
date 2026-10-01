"""Сроки кейсов (ADR-0016 §4): SLA P0–P2 идёт в 08:00–23:00 по Белграду, апелляции — сутки."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.moderation.domain.queues import Queue, stricter
from app.modules.moderation.domain.sla import add_working_time, due_at

pytestmark = pytest.mark.unit


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


@pytest.mark.parametrize(
    ("queue", "opened", "due"),
    [
        (Queue.PREMOD, utc(2026, 10, 1, 8, 0), utc(2026, 10, 1, 8, 30)),  # 10:00 → 10:30
        (Queue.SAFETY, utc(2026, 10, 1, 8, 0), utc(2026, 10, 1, 9, 0)),
        (Queue.FRAUD, utc(2026, 10, 1, 8, 0), utc(2026, 10, 1, 10, 0)),
        # 22:50 по Белграду: 10 минут сегодня, 20 — завтра с 08:00
        (Queue.PREMOD, utc(2026, 10, 1, 20, 50), utc(2026, 10, 2, 6, 20)),
        # ночь: срок пошёл в 08:00
        (Queue.SAFETY, utc(2026, 10, 1, 0, 0), utc(2026, 10, 1, 7, 0)),
        (Queue.FRAUD, utc(2026, 10, 1, 21, 0), utc(2026, 10, 2, 8, 0)),  # ровно в 23:00
        # апелляции — календарные 72 часа
        (Queue.APPEALS, utc(2026, 10, 1, 21, 0), utc(2026, 10, 4, 21, 0)),
    ],
)
def test_due_at_counts_working_hours(queue: Queue, opened: datetime, due: datetime) -> None:
    assert due_at(queue, opened) == due


def test_winter_time_change_does_not_shift_the_deadline() -> None:
    # 25 октября 2026 — переход на зимнее время ночью: утром Белград — UTC+1
    opened = utc(2026, 10, 24, 20, 45)  # 22:45 летнего времени
    assert due_at(Queue.FRAUD, opened) == utc(2026, 10, 25, 8, 45)  # 15 мин + 1:45 с 08:00 (UTC+1)


def test_long_duration_spans_several_days() -> None:
    assert add_working_time(utc(2026, 10, 1, 6, 0), timedelta(hours=31)) == utc(2026, 10, 3, 7, 0)


def test_stricter_queue_wins() -> None:
    assert stricter(Queue.PREMOD, Queue.SAFETY) is Queue.SAFETY
    assert stricter(Queue.FRAUD, Queue.APPEALS) is Queue.FRAUD
    assert stricter(Queue.PREMOD, Queue.PREMOD) is Queue.PREMOD
