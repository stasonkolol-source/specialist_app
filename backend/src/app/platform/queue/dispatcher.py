"""Диспетчер доменных событий (ADR-0008 п. 3, ADR-0020 §4).

При commit UoW ставит по задаче на каждого подписчика события — на том же соединении,
в той же транзакции. Реестр подписок собирает entrypoints/_wiring из tasks.py модулей.
"""

from collections import defaultdict
from collections.abc import Iterable

from app.platform.kernel.events import DomainEvent
from app.platform.queue.port import JobQueue, TaskRef


class EventRegistry:
    """Тип события → задачи-подписчики. Payload подписчика — само событие."""

    def __init__(self) -> None:
        self._subscribers: dict[type[DomainEvent], list[TaskRef[DomainEvent]]] = defaultdict(list)

    def subscribe[E: DomainEvent](self, event_type: type[E], task: TaskRef[E]) -> None:
        if task.payload is not event_type:
            raise TypeError(f"{task.name}: payload type must be {event_type.__name__}")
        subscribers = self._subscribers[event_type]
        if any(t.name == task.name for t in subscribers):
            raise ValueError(f"{task.name} is already subscribed to {event_type.__name__}")
        subscribers.append(task)

    def subscribers(self, event: DomainEvent) -> list[TaskRef[DomainEvent]]:
        return list(self._subscribers.get(type(event), ()))

    def without(self, *names: str) -> EventRegistry:
        """Копия реестра без этих подписчиков: имя задачи или префикс с точкой на конце
        (`analytics.`). Для процесса, которому их работа не нужна: `cli seed-demo` сам одобряет
        свои профили, а демо-данные не идут в аналитику и ленты уведомлений."""

        def dropped(task: TaskRef[DomainEvent]) -> bool:
            return any(
                task.name.startswith(name) if name.endswith(".") else task.name == name
                for name in names
            )

        copy = EventRegistry()
        for event_type, tasks in self._subscribers.items():
            copy._subscribers[event_type] = [task for task in tasks if not dropped(task)]
        return copy


class EventDispatcher:
    def __init__(self, registry: EventRegistry, queue: JobQueue) -> None:
        self._registry = registry
        self._queue = queue

    async def enqueue(self, events: Iterable[DomainEvent]) -> None:
        """По задаче на подписчика; dedup — по паре (задача, event_id). Подписчик с `delay`
        стартует не раньше occurred_at + delay."""
        for event in events:
            for task in self._registry.subscribers(event):
                not_before = event.occurred_at + task.delay if task.delay is not None else None
                await self._queue.enqueue(
                    task, event, dedup_key=str(event.event_id), not_before=not_before
                )
