"""Поставленные задачи в тестах (ADR-0020 §11): фейков очереди нет, смотрим в БД."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class QueuedTask:
    task_name: str
    queue: str
    payload: dict[str, Any]
    queueing_lock: str | None
    scheduled_at: datetime | None = None
    """Не раньше — `not_before` постановки; None — сразу."""


async def queued_tasks(session: AsyncSession, task_name: str | None = None) -> list[QueuedTask]:
    """Задачи в статусе todo, видимые из текущей транзакции сессии."""
    rows = await session.execute(
        text(
            "SELECT task_name, queue_name, args, queueing_lock, scheduled_at"
            " FROM procrastinate_jobs WHERE status = 'todo'"
            " AND (CAST(:name AS text) IS NULL OR task_name = :name) ORDER BY id"
        ),
        {"name": task_name},
    )
    return [
        QueuedTask(
            task_name=r.task_name,
            queue=r.queue_name,
            payload=dict(r.args.get("payload", {})),
            queueing_lock=r.queueing_lock,
            scheduled_at=r.scheduled_at,
        )
        for r in rows
    ]
