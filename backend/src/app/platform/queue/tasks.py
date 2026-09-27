"""Обёртка фоновых задач (ADR-0020 §3, §9; ARCHITECTURE §12).

Модуль объявляет задачу в своём tasks.py:

    @task(DELETE_OBJECT)
    async def delete_object(payload: DeleteObjectPayload, storage: FromDishka[StoragePort]) -> None:
        ...

Декоратор только записывает спецификацию в декларативный реестр (он не держит соединений).
Воркер регистрирует задачи в приложении Procrastinate под именем из TaskRef — web и бот
ставят их по тому же имени. Каждое выполнение: свой REQUEST scope dishka, валидация
payload через TypeAdapter, контекст логов, отображение ошибок по таблице ADR-0020 §9.
"""

import inspect
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, get_type_hints

import procrastinate
import sentry_sdk
import structlog
from dishka import AsyncContainer
from procrastinate.jobs import Job
from procrastinate.retry import BaseRetryStrategy, RetryDecision
from pydantic import TypeAdapter

from app.platform.kernel.errors import (
    ConcurrentModificationError,
    ConflictError,
    DomainValidationError,
    ExternalServiceError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
)
from app.platform.kernel.events import DomainEvent
from app.platform.observability.logging import bind_context, clear_context
from app.platform.queue.dispatcher import EventRegistry
from app.platform.queue.port import TaskRef

log = structlog.get_logger(__name__)

CONTAINER_KEY = "container"
"""Ключ additional_context воркера: контейнер dishka процесса."""

QUEUES = ("default", "notifications", "media")


@dataclass(frozen=True, slots=True)
class JitteredRetry(BaseRetryStrategy):
    """Экспоненциальная задержка с джиттером; RateLimitedError — через retry_after."""

    max_attempts: int = 6
    """Всего запусков, включая первый (в Procrastinate job.attempts — число прошлых)."""
    base_seconds: float = 5.0
    cap_seconds: float = 600.0

    def get_retry_decision(self, *, exception: BaseException, job: Job) -> RetryDecision | None:
        if job.attempts + 1 >= self.max_attempts:
            return None
        if isinstance(exception, RateLimitedError):
            return RetryDecision(retry_in={"seconds": max(1, exception.retry_after)})
        wait = min(self.cap_seconds, self.base_seconds * 2**job.attempts)
        wait *= random.uniform(0.5, 1.5)  # noqa: S311 — джиттер, не криптография
        return RetryDecision(retry_in={"seconds": round(wait)})


DEFAULT_RETRY = JitteredRetry()

Handler = Callable[..., Awaitable[None]]


@dataclass(frozen=True, slots=True)
class TaskSpec:
    ref: TaskRef[Any]
    handler: Handler
    retry: BaseRetryStrategy | None = DEFAULT_RETRY


@dataclass(frozen=True, slots=True)
class PeriodicRun:
    """Контекст запуска периодической задачи: приложение, контейнер и плановое время (unix)."""

    app: procrastinate.App
    container: AsyncContainer
    timestamp: int


PeriodicHandler = Callable[[PeriodicRun], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class PeriodicSpec:
    name: str
    cron: str
    handler: PeriodicHandler
    queue: str = "default"


@dataclass
class TaskRegistry:
    """Декларативный реестр задач процесса: заполняется декораторами при импорте tasks.py."""

    tasks: dict[str, TaskSpec] = field(default_factory=dict)
    periodic: dict[str, PeriodicSpec] = field(default_factory=dict)
    subscriptions: list[tuple[type[DomainEvent], TaskRef[Any]]] = field(default_factory=list)

    def add(self, spec: TaskSpec) -> None:
        if spec.ref.name in self.tasks:
            raise ValueError(f"task {spec.ref.name} is declared twice")
        self.tasks[spec.ref.name] = spec

    def add_periodic(self, spec: PeriodicSpec) -> None:
        if spec.name in self.periodic:
            raise ValueError(f"periodic task {spec.name} is declared twice")
        self.periodic[spec.name] = spec

    def event_registry(self) -> EventRegistry:
        """Подписки для диспетчера событий — одинаковые в web, bot и worker."""
        registry = EventRegistry()
        for event_type, ref in self.subscriptions:
            registry.subscribe(event_type, ref)
        return registry


TASKS = TaskRegistry()


def task[P](
    ref: TaskRef[P],
    *,
    retry: BaseRetryStrategy | None = DEFAULT_RETRY,
    registry: TaskRegistry = TASKS,
) -> Callable[[Handler], Handler]:
    """Объявить обработчик задачи. Первый параметр — payload, остальные — FromDishka[...]."""

    def decorator(handler: Handler) -> Handler:
        registry.add(TaskSpec(ref=ref, handler=handler, retry=retry))
        return handler

    return decorator


def subscriber[E: DomainEvent](
    event_type: type[E],
    ref: TaskRef[E],
    *,
    retry: BaseRetryStrategy | None = DEFAULT_RETRY,
    registry: TaskRegistry = TASKS,
) -> Callable[[Handler], Handler]:
    """Задача-подписчик события: payload — само событие, dedup — по (задача, event_id)."""

    def decorator(handler: Handler) -> Handler:
        registry.add(TaskSpec(ref=ref, handler=handler, retry=retry))
        registry.subscriptions.append((event_type, ref))
        return handler

    return decorator


def periodic(
    name: str, *, cron: str, queue: str = "default", registry: TaskRegistry = TASKS
) -> Callable[[PeriodicHandler], PeriodicHandler]:
    """Объявить периодическую задачу (cron). Обработчик получает PeriodicRun."""

    def decorator(handler: PeriodicHandler) -> PeriodicHandler:
        registry.add_periodic(PeriodicSpec(name=name, cron=cron, handler=handler, queue=queue))
        return handler

    return decorator


def _dependencies(handler: Handler) -> list[tuple[str, Any]]:
    """Параметры обработчика после payload: (имя, тип) из FromDishka[T]."""
    hints = get_type_hints(handler, include_extras=True)
    params = list(inspect.signature(handler).parameters)[1:]
    deps: list[tuple[str, Any]] = []
    for name in params:
        hint = hints.get(name)
        args = getattr(hint, "__metadata__", None)
        if args is None:
            raise TypeError(f"{handler.__qualname__}: parameter {name} must be FromDishka[...]")
        deps.append((name, hint.__origin__))  # type: ignore[union-attr]  # Annotated[T, …]
    return deps


async def run_task(
    spec: TaskSpec, container: AsyncContainer, payload: dict[str, Any], *, job_id: int | None = None
) -> None:
    """Выполнить задачу в своём REQUEST scope с отображением ошибок по ADR-0020 §9."""
    data = TypeAdapter(spec.ref.payload).validate_python(payload)
    event_id = payload.get("event_id")
    bind_context(
        job_id=str(job_id) if job_id is not None else None,
        request_id=None,
        trace_id=str(event_id) if event_id else None,
    )
    try:
        async with container() as request:
            kwargs = {name: await request.get(tp) for name, tp in _dependencies(spec.handler)}
            await spec.handler(data, **kwargs)
    except ConcurrentModificationError:
        raise  # повтор: строку изменили параллельно
    except NotFoundError as exc:
        log.warning("task_target_not_found", task=spec.ref.name, code=exc.code)
    except ForbiddenError as exc:
        log.warning("task_forbidden", task=spec.ref.name, code=exc.code)
    except ConflictError as exc:
        log.info("task_state_already_changed", task=spec.ref.name, code=exc.code)
    except DomainValidationError as exc:
        log.error("task_payload_rejected", task=spec.ref.name, code=exc.code)
    except RateLimitedError, ExternalServiceError:
        raise  # повтор по стратегии
    except Exception:
        sentry_sdk.capture_exception()
        log.exception("task_failed", task=spec.ref.name)
        raise
    finally:
        clear_context()


def register_tasks(app: procrastinate.App, registry: TaskRegistry = TASKS) -> None:
    """Зарегистрировать задачи и периодические задачи в приложении воркера."""
    for spec in registry.tasks.values():
        app.task(
            name=spec.ref.name, queue=spec.ref.queue, retry=spec.retry or False, pass_context=True
        )(_procrastinate_entry(spec))
    for p in registry.periodic.values():
        app.periodic(cron=p.cron, periodic_id=p.name)(
            app.task(name=p.name, queue=p.queue, pass_context=True)(_periodic_entry(p))
        )


def _procrastinate_entry(spec: TaskSpec) -> Callable[..., Awaitable[None]]:
    async def entry(context: procrastinate.JobContext, payload: dict[str, Any]) -> None:
        container = context.additional_context[CONTAINER_KEY]
        job_id = context.job.id if context.job else None
        await run_task(spec, container, payload, job_id=job_id)

    entry.__name__ = spec.ref.name.replace(".", "_")
    return entry


def _periodic_entry(spec: PeriodicSpec) -> Callable[..., Awaitable[None]]:
    async def entry(context: procrastinate.JobContext, timestamp: int) -> None:
        container = context.additional_context[CONTAINER_KEY]
        await spec.handler(PeriodicRun(app=context.app, container=container, timestamp=timestamp))

    entry.__name__ = spec.name.replace(".", "_")
    return entry
