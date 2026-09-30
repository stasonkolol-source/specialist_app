"""Лаг очередей (DEVELOPMENT_PLAN 2.3b, ARCHITECTURE §12.4): возраст самой старой готовой задачи.

Отложенная задача ждёт с `scheduled_at`, а не с постановки: уведомление, отложенное до утра
тихими часами, ночью не опаздывает.
"""

from dataclasses import dataclass
from datetime import timedelta

import procrastinate
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.kernel.clock import SystemClock
from app.platform.kernel.ids import new_id
from app.platform.queue.lag import queue_lags
from app.platform.queue.port import TaskRef
from app.platform.queue.procrastinate_queue import ProcrastinateJobQueue

pytestmark = pytest.mark.integration


@dataclass(frozen=True, slots=True)
class Ping:
    n: int


def ping() -> TaskRef[Ping]:
    """Своя очередь на тест: задачи других тестов (API-тесты коммитят) лаг не искажают."""
    return TaskRef("test.lag_ping", Ping, queue=f"lag-{new_id().hex[:12]}")


async def age(session: AsyncSession, task: TaskRef[Ping], minutes: int) -> None:
    """Задачи теста поставлены `minutes` минут назад."""
    await session.execute(
        text(
            "UPDATE procrastinate_events SET at = now() - make_interval(mins => :m)"
            " WHERE job_id IN (SELECT id FROM procrastinate_jobs WHERE queue_name = :queue)"
        ),
        {"m": minutes, "queue": task.queue},
    )


async def test_lag_is_the_age_of_the_oldest_runnable_job(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    queue, task = ProcrastinateJobQueue(db_session, procrastinate_app), ping()
    await queue.enqueue(task, Ping(n=1))
    await queue.enqueue(task, Ping(n=2), not_before=SystemClock().now() + timedelta(hours=8))
    await age(db_session, task, 5)

    lags = await queue_lags(db_session)

    assert 295 <= lags[task.queue] < 360  # отложенная до утра в лаг не входит


async def test_job_scheduled_in_the_past_waits_since_its_time(
    db_session: AsyncSession, procrastinate_app: procrastinate.App
) -> None:
    queue, task = ProcrastinateJobQueue(db_session, procrastinate_app), ping()
    await queue.enqueue(task, Ping(n=1), not_before=SystemClock().now() - timedelta(minutes=1))
    await age(db_session, task, 60)  # поставлена час назад, но ждать её велели до минуты назад

    lags = await queue_lags(db_session)

    assert 55 <= lags[task.queue] < 120  # now() базы — начало транзакции теста
