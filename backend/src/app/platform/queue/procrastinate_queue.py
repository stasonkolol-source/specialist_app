"""Адаптер JobQueue на Procrastinate (ADR-0008, docs/spikes/0.8).

Задача ставится на соединении текущей транзакции сессии SQLAlchemy — атомарно с данными.
Каждая постановка — под savepoint psycopg (`raw.transaction()`): savepoint SQLAlchemy
ленивый и вставку мимо него не защищает. AlreadyEnqueued — успех: задача уже стоит.
"""

from datetime import datetime
from typing import Any

import procrastinate
import psycopg
import structlog
from procrastinate.exceptions import AlreadyEnqueued
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.queue.port import TaskRef

log = structlog.get_logger(__name__)


def dump_payload[P](task: TaskRef[P], payload: P) -> dict[str, Any]:
    """Payload в JSON-совместимый dict по схеме dataclass (валидирует обёртка задач, 0.12)."""
    data = TypeAdapter(task.payload).dump_python(payload, mode="json")
    if not isinstance(data, dict):
        raise TypeError(f"{task.name}: payload must be a dataclass, got {type(payload).__name__}")
    return data


async def session_driver_connection(session: AsyncSession) -> psycopg.AsyncConnection[Any]:
    """psycopg-соединение текущей транзакции сессии."""
    connection = await session.connection()
    raw = await connection.get_raw_connection()
    driver = raw.driver_connection
    if not isinstance(driver, psycopg.AsyncConnection):
        raise TypeError("session is not bound to a psycopg async connection")
    return driver


class ProcrastinateJobQueue:
    def __init__(self, session: AsyncSession, app: procrastinate.App) -> None:
        self._session = session
        self._app = app

    async def enqueue[P](
        self,
        task: TaskRef[P],
        payload: P,
        *,
        dedup_key: str | None = None,
        not_before: datetime | None = None,
    ) -> None:
        raw = await session_driver_connection(self._session)
        # queueing_lock в Procrastinate общий на все задачи: ключ — в пространстве своей задачи
        lock = f"{task.name}:{dedup_key}" if dedup_key is not None else None
        deferrer = self._app.configure_task(
            name=task.name,
            queue=task.queue,
            queueing_lock=lock,
            schedule_at=not_before,
            connection=raw,
        )
        try:
            async with raw.transaction():  # в активной транзакции — SAVEPOINT
                await deferrer.defer_async(payload=dump_payload(task, payload))
        except AlreadyEnqueued:
            log.debug("task_already_enqueued", task=task.name, dedup_key=dedup_key)
