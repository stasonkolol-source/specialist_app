"""Построители заявок для тестов jobs."""

from datetime import UTC, datetime
from typing import Any

from app.modules.jobs.domain.job import (
    Budget,
    BudgetType,
    Job,
    JobContent,
    JobId,
    Place,
    Urgency,
)
from app.platform.kernel.ids import CategoryId, CityId, UserId, new_id

NOW = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
CLIENT = UserId(new_id())
ELECTRICAL = CategoryId(5)


def content(**fields: Any) -> JobContent:
    values: dict[str, Any] = {
        "title": "Повесить люстру в спальне",
        "description": "Люстра на 5 рожков, потолок 2,7 м, крюк есть.",
        "category_id": ELECTRICAL,
        "category_path": (CategoryId(1), ELECTRICAL),
        "urgency": Urgency.THIS_WEEK,
        "budget": Budget(type=BudgetType.FIXED, min=500_000),
        "place": Place(city_id=CityId(1)),
        "content_lang": "ru",
    }
    values.update(fields)
    return JobContent(**values)


def submitted(client_id: UserId = CLIENT, **fields: Any) -> Job:
    job = Job.submit(
        job_id=JobId(new_id()),
        client_id=client_id,
        content=content(**fields),
        max_responses=5,
        now=NOW,
    )
    job.pull_events()
    job.pull_history()
    return job


def published(client_id: UserId = CLIENT, **fields: Any) -> Job:
    job = submitted(client_id, **fields)
    assert job.approve(version=None, now=NOW)
    job.pull_events()
    job.pull_history()
    return job
