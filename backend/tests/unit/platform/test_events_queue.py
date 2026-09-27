"""Реестр подписок и сериализация payload задач (DEVELOPMENT_PLAN 0.10)."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import TypeAdapter

from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import new_id
from app.platform.queue.dispatcher import EventDispatcher, EventRegistry
from app.platform.queue.port import TaskRef
from app.platform.queue.procrastinate_queue import dump_payload

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True, kw_only=True)
class JobPublished(DomainEvent):
    event_type = "jobs.JobPublished"
    job_id: UUID
    title: str


@dataclass(frozen=True, slots=True, kw_only=True)
class JobClosed(DomainEvent):
    event_type = "jobs.JobClosed"
    job_id: UUID


MATCH_ALERTS = TaskRef("jobs.match_alerts", JobPublished, queue="notifications")
REINDEX = TaskRef("search.reindex_job", JobPublished)


def test_registry_returns_subscribers_by_event_type() -> None:
    registry = EventRegistry()
    registry.subscribe(JobPublished, MATCH_ALERTS)
    registry.subscribe(JobPublished, REINDEX)
    event = JobPublished(job_id=new_id(), title="Люстра", occurred_at=NOW)
    assert [t.name for t in registry.subscribers(event)] == [
        "jobs.match_alerts",
        "search.reindex_job",
    ]
    assert registry.subscribers(JobClosed(job_id=new_id(), occurred_at=NOW)) == []


def test_registry_rejects_mismatched_payload_and_duplicates() -> None:
    registry = EventRegistry()
    with pytest.raises(TypeError):
        registry.subscribe(JobClosed, MATCH_ALERTS)  # type: ignore[arg-type]
    registry.subscribe(JobPublished, MATCH_ALERTS)
    with pytest.raises(ValueError, match="already subscribed"):
        registry.subscribe(JobPublished, MATCH_ALERTS)


def test_event_payload_roundtrip_through_json() -> None:
    event = JobPublished(job_id=new_id(), title="Люстра", occurred_at=NOW)
    data = dump_payload(MATCH_ALERTS, event)
    assert data["job_id"] == str(event.job_id)
    assert data["title"] == "Люстра"
    assert data["event_id"] == str(event.event_id)
    restored = TypeAdapter(JobPublished).validate_python(data)
    assert restored == event


async def test_dispatcher_enqueues_one_task_per_subscriber_with_dedup_key() -> None:
    calls: list[tuple[str, str | None]] = []

    class RecordingQueue:
        async def enqueue(
            self, task: TaskRef[object], payload: object, *, dedup_key: str | None = None
        ) -> None:
            calls.append((task.name, dedup_key))

    registry = EventRegistry()
    registry.subscribe(JobPublished, MATCH_ALERTS)
    registry.subscribe(JobPublished, REINDEX)
    event = JobPublished(job_id=new_id(), title="x", occurred_at=NOW)
    await EventDispatcher(registry, RecordingQueue()).enqueue([event])
    assert calls == [
        ("jobs.match_alerts", f"jobs.match_alerts:{event.event_id}"),
        ("search.reindex_job", f"search.reindex_job:{event.event_id}"),
    ]
