"""Порт очереди задач (ADR-0020 §3, ADR-0008).

Use case ссылается на задачу типизированной константой `TaskRef`, payload — frozen
dataclass. Задача ставится в той же транзакции, что и данные, и выполнится после commit.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TaskRef[P]:
    name: str
    """`<модуль>.<глагол>_<объект>` (ARCHITECTURE §12.3)."""
    payload: type[P]
    queue: str = "default"


class JobQueue(Protocol):
    async def enqueue[P](
        self,
        task: TaskRef[P],
        payload: P,
        *,
        dedup_key: str | None = None,
        not_before: datetime | None = None,
        priority: int = 0,
    ) -> None:
        """Поставить задачу в текущей транзакции. Пока задача с тем же `dedup_key` ждёт в
        очереди, вторая не ставится — это не ошибка. Ключ действует в пределах своей задачи.
        `not_before` — не запускать раньше (тихие часы, пауза после 429); None — сразу.
        `priority` — из ждущих в очереди раньше берутся задачи с большим (при перегрузке)."""
        ...
