"""Напоминания об отзыве (DEVELOPMENT_PLAN 7.2; ARCHITECTURE §7.9): через сутки после
завершения и за 2 дня до конца окна в 14 дней; после окна и после последнего — тишина."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.reviews.domain.request import RequestStage, due_stage

pytestmark = pytest.mark.unit

DONE = datetime(2026, 10, 1, 18, 0, tzinfo=UTC)
HOUR, DAY = timedelta(hours=1), timedelta(days=1)


def stage(
    after: timedelta,
    *,
    reminded: bool = False,
    last_call: bool = False,
) -> RequestStage | None:
    now = DONE + after
    return due_stage(
        completed_at=DONE,
        reminded_at=DONE + DAY if reminded else None,
        last_call_at=DONE + 12 * DAY if last_call else None,
        now=now,
    )


@pytest.mark.parametrize(
    ("after", "reminded", "expected"),
    [
        (23 * HOUR, False, None),  # сутки ещё не прошли
        (DAY, False, RequestStage.REMINDER),
        (5 * DAY, False, RequestStage.REMINDER),  # воркер стоял — напомним сейчас
        (5 * DAY, True, None),  # уже напомнили
        (12 * DAY - HOUR, True, None),
        (12 * DAY, True, RequestStage.LAST_CALL),  # за 2 дня до конца окна
        (13 * DAY, False, RequestStage.LAST_CALL),  # оба просрочены — только последнее
        (14 * DAY, True, None),  # окно закрылось
    ],
)
def test_reminder_then_last_call_while_the_window_is_open(
    after: timedelta, reminded: bool, expected: RequestStage | None
) -> None:
    assert stage(after, reminded=reminded) is expected


def test_nothing_after_the_last_call() -> None:
    assert stage(13 * DAY, reminded=True, last_call=True) is None
