"""Просьба оставить отзыв (DEVELOPMENT_PLAN 7.2; ARCHITECTURE §7.9, §12.3): клиент получает
`review.request`, когда сделка завершена, напоминание — через сутки и за 2 дня до конца окна в
14 дней; оставил отзыв или окно закрылось — больше не просим."""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from app.modules.reviews.domain.review import REVIEW_WINDOW

REMINDER_AFTER: Final = timedelta(hours=24)
LAST_CALL_BEFORE: Final = timedelta(days=2)


class RequestStage(StrEnum):
    FIRST = "first"
    REMINDER = "reminder"
    LAST_CALL = "last_call"


def due_stage(
    *,
    completed_at: datetime,
    reminded_at: datetime | None,
    last_call_at: datetime | None,
    now: datetime,
) -> RequestStage | None:
    """Какое напоминание пора отправить; оба просрочены (воркер стоял) — только последнее."""
    closes = completed_at + REVIEW_WINDOW
    if now >= closes or last_call_at is not None:
        return None
    if now >= closes - LAST_CALL_BEFORE:
        return RequestStage.LAST_CALL
    if reminded_at is None and now >= completed_at + REMINDER_AFTER:
        return RequestStage.REMINDER
    return None
