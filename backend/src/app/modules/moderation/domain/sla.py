"""Сроки кейсов (ADR-0016 §4, ARCHITECTURE §14.2): SLA — время решения человеком.

Модераторы работают 08:00–23:00 по Белграду: срок P0–P2 идёт только в эти часы (кейс,
открытый в 22:50 с SLA 30 мин, надо решить к 08:20). Апелляции — 72 календарных часа
**[Допущение]**: трое суток, а не 72 рабочих часа (почти пять дней).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from app.modules.moderation.domain.queues import Queue
from app.platform.kernel.clock import BUSINESS_TZ

WORKDAY_START: Final = time(8, 0)
WORKDAY_END: Final = time(23, 0)


@dataclass(frozen=True, slots=True)
class Sla:
    duration: timedelta
    working_hours: bool
    """Срок идёт только в часы работы модераторов."""


SLA: Final[Mapping[Queue, Sla]] = {
    Queue.SAFETY: Sla(timedelta(hours=1), working_hours=True),
    Queue.FRAUD: Sla(timedelta(hours=2), working_hours=True),
    Queue.PREMOD: Sla(timedelta(minutes=30), working_hours=True),
    Queue.APPEALS: Sla(timedelta(hours=72), working_hours=False),
}


def due_at(queue: Queue, opened_at: datetime) -> datetime:
    """Срок решения кейса, открытого в `opened_at` (UTC)."""
    sla = SLA[queue]
    if not sla.working_hours:
        return opened_at + sla.duration
    return add_working_time(opened_at, sla.duration)


def add_working_time(
    start: datetime, duration: timedelta, *, tz: ZoneInfo = BUSINESS_TZ
) -> datetime:
    """`start` плюс `duration` рабочего времени 08:00–23:00 в `tz`. Переход на летнее время —
    ночью, вне рабочих часов: внутри рабочего дня часы идут ровно."""
    local = start.astimezone(tz)
    remaining = duration
    while True:
        opens = datetime.combine(local.date(), WORKDAY_START, tzinfo=tz)
        closes = datetime.combine(local.date(), WORKDAY_END, tzinfo=tz)
        local = max(local, opens)
        if local < closes:
            if remaining <= closes - local:
                return (local + remaining).astimezone(UTC)
            remaining -= closes - local
        local = datetime.combine(local.date() + timedelta(days=1), WORKDAY_START, tzinfo=tz)


def dispute_due_at(queue: Queue, opened_at: datetime, respond_by: datetime) -> datetime:
    """Срок кейса спора: P0 — сразу по SLA (угрозы не ждут); P1 — SLA с конца 48 ч на ответ:
    решать раньше, чем ответит вторая сторона, модератору нечего. Ответ раньше срока
    приближает его (Case.add_trigger)."""
    if queue is Queue.SAFETY:
        return due_at(queue, opened_at)
    return due_at(queue, max(opened_at, respond_by))
