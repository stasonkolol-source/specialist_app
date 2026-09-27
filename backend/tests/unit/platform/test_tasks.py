"""Обёртка фоновых задач: повторы и отображение ошибок (DEVELOPMENT_PLAN 0.12, ADR-0020 §9)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

import pytest
from dishka import FromDishka, Provider, Scope, make_async_container, provide
from procrastinate.jobs import Job
from pydantic import ValidationError
from structlog.testing import capture_logs

from app.platform.kernel.errors import (
    ConcurrentModificationError,
    ConflictError,
    DomainError,
    DomainValidationError,
    ExternalServiceError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
)
from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import new_id
from app.platform.queue.port import TaskRef
from app.platform.queue.tasks import (
    JitteredRetry,
    PeriodicRun,
    TaskRegistry,
    TaskSpec,
    periodic,
    run_task,
    subscriber,
    task,
)

pytestmark = pytest.mark.unit


def _job(attempts: int) -> Job:
    return Job(
        id=1, queue="default", lock=None, queueing_lock=None, task_name="t", attempts=attempts
    )


@dataclass(frozen=True, slots=True)
class Note:
    text: str


NOTE: Final = TaskRef("sample.note", Note)


class Greeter:
    def greet(self, text: str) -> str:
        return f"привет, {text}"


class GreeterProvider(Provider):
    greeter = provide(Greeter, scope=Scope.REQUEST)


# --- retry --------------------------------------------------------------------------------


def _delay(strategy: JitteredRetry, attempts: int, exc: Exception | None = None) -> float | None:
    before = datetime.now(UTC)
    decision = strategy.get_retry_decision(exception=exc or RuntimeError(), job=_job(attempts))
    if decision is None:
        return None
    assert decision.retry_at is not None
    return (decision.retry_at - before).total_seconds()


@pytest.mark.parametrize(("attempts", "low", "high"), [(0, 2.5, 7.5), (1, 5, 15), (3, 20, 60)])
def test_retry_delay_grows_exponentially_with_jitter(
    attempts: int, low: float, high: float
) -> None:
    strategy = JitteredRetry(max_attempts=6, base_seconds=5, cap_seconds=600)
    delays = [_delay(strategy, attempts) for _ in range(100)]
    assert all(d is not None and low - 1 <= d <= high + 1 for d in delays)
    assert len(set(delays)) > 1  # джиттер разводит повторы разных задач


def test_retry_delay_is_capped() -> None:
    delay = _delay(JitteredRetry(max_attempts=20, base_seconds=5, cap_seconds=60), attempts=15)
    assert delay is not None
    assert delay <= 60 * 1.5 + 1


def test_retry_stops_after_max_attempts() -> None:
    strategy = JitteredRetry(max_attempts=3)
    assert _delay(strategy, attempts=1) is not None
    assert _delay(strategy, attempts=2) is None


def test_rate_limited_waits_retry_after() -> None:
    delay = _delay(JitteredRetry(), attempts=0, exc=RateLimitedError(retry_after=42))
    assert delay is not None
    assert round(delay) == 42


# --- registry -----------------------------------------------------------------------------


def test_registry_rejects_duplicate_names() -> None:
    registry = TaskRegistry()

    @task(NOTE, registry=registry)
    async def first(payload: Note) -> None: ...

    with pytest.raises(ValueError, match="declared twice"):

        @task(NOTE, registry=registry)
        async def second(payload: Note) -> None: ...

    @periodic("ops.tick", cron="* * * * *", registry=registry)
    async def tick(run: PeriodicRun) -> None: ...

    with pytest.raises(ValueError, match="declared twice"):

        @periodic("ops.tick", cron="* * * * *", registry=registry)
        async def tick_again(run: PeriodicRun) -> None: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class Pinged(DomainEvent):
    event_type = "sample.Pinged"
    target: UUID


ON_PINGED: Final = TaskRef("sample.on_pinged", Pinged)


def test_subscriber_is_a_task_and_an_event_subscription() -> None:
    registry = TaskRegistry()

    @subscriber(Pinged, ON_PINGED, registry=registry)
    async def on_pinged(event: Pinged) -> None: ...

    assert registry.tasks[ON_PINGED.name].handler is on_pinged
    event = Pinged(target=new_id(), occurred_at=datetime.now(UTC))
    assert registry.event_registry().subscribers(event) == [ON_PINGED]


# --- run_task -----------------------------------------------------------------------------


async def test_run_task_validates_payload_and_injects_dependencies() -> None:
    seen: list[str] = []

    async def handler(payload: Note, greeter: FromDishka[Greeter]) -> None:
        seen.append(greeter.greet(payload.text))

    container = make_async_container(GreeterProvider())
    try:
        await run_task(TaskSpec(NOTE, handler), container, {"text": "сосед"}, job_id=7)
        with pytest.raises(ValidationError):
            await run_task(TaskSpec(NOTE, handler), container, {"txt": "опечатка"})
    finally:
        await container.close()
    assert seen == ["привет, сосед"]


async def test_run_task_rejects_parameters_without_from_dishka() -> None:
    async def handler(payload: Note, greeter: Greeter) -> None: ...

    container = make_async_container(GreeterProvider())
    try:
        with pytest.raises(TypeError, match="FromDishka"):
            await run_task(TaskSpec(NOTE, handler), container, {"text": "x"})
    finally:
        await container.close()


@pytest.mark.parametrize(
    ("error", "log_event"),
    [
        (NotFoundError(), "task_target_not_found"),
        (ForbiddenError(), "task_forbidden"),
        (ConflictError(), "task_state_already_changed"),
        (DomainValidationError(), "task_payload_rejected"),
    ],
)
async def test_final_domain_errors_are_logged_not_retried(
    error: DomainError, log_event: str
) -> None:
    async def handler(payload: Note) -> None:
        raise error

    container = make_async_container(Provider())
    try:
        with capture_logs() as logs:
            await run_task(TaskSpec(NOTE, handler), container, {"text": "x"})
    finally:
        await container.close()
    assert [entry["event"] for entry in logs] == [log_event]


@pytest.mark.parametrize(
    "error",
    [
        ConcurrentModificationError(),
        RateLimitedError(retry_after=5),
        ExternalServiceError(),
        RuntimeError("bug"),
    ],
)
async def test_transient_and_unexpected_errors_are_reraised(error: Exception) -> None:
    async def handler(payload: Note) -> None:
        raise error

    container = make_async_container(Provider())
    try:
        with pytest.raises(type(error)):
            await run_task(TaskSpec(NOTE, handler), container, {"text": "x"})
    finally:
        await container.close()
