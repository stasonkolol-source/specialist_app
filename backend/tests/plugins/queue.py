"""Задачи-подписчики в API-тестах: выполнить поставленные задачи так, как это сделал бы воркер.

API-тесты коммитят данные, поэтому в procrastinate_jobs лежат задачи и других тестов:
берём только задачи своего пользователя (`user_id` в payload события), снимаем их с
очереди и выполняем обёрткой воркера (`run_task`: свой REQUEST scope, TypeAdapter,
отображение ошибок ADR-0020 §9).
"""

from typing import Any
from uuid import UUID

from dishka import AsyncContainer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.platform.queue.port import TaskRef
from app.platform.queue.tasks import TASKS, run_task


async def run_queued(container: AsyncContainer, task: TaskRef[Any], *, user_id: UUID) -> int:
    """Выполнить задачи `task` пользователя `user_id`; вернуть, сколько их было."""
    spec = TASKS.tasks[task.name]
    async with container() as request:
        engine = await request.get(AsyncEngine)
    async with engine.begin() as conn:
        rows = (
            await conn.execute(
                text(
                    "DELETE FROM procrastinate_jobs WHERE task_name = :name AND status = 'todo'"
                    " AND args->'payload'->>'user_id' = :user_id RETURNING id, args"
                ),
                {"name": task.name, "user_id": str(user_id)},
            )
        ).all()
    for row in sorted(rows, key=lambda r: r.id):
        await run_task(spec, container, row.args["payload"], job_id=row.id)
    return len(rows)
