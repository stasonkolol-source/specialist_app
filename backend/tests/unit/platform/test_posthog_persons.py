"""Удаление персоны в PostHog по UserDeleted (DEVELOPMENT_PLAN 2.12b, K32a) и молчание аналитики
об удалённых аккаунтах."""

import json
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from dishka import make_async_container
from pydantic import SecretStr
from structlog.testing import capture_logs

from app.platform.analytics.events import EventName, analytics_event
from app.platform.analytics.fake import LoggingAnalytics
from app.platform.analytics.port import AnalyticsEvent, PersonDeletion
from app.platform.analytics.posthog import PostHogAnalytics
from app.platform.analytics.posthog_dashboard import client_for
from app.platform.analytics.posthog_persons import (
    NoPersonDeletion,
    PostHogPersons,
    PostHogPersonsError,
)
from app.platform.analytics.tasks import (
    FORGET_PERSON,
    FORGET_PERSON_AGAIN,
    FORGET_RETRY,
    forget_person,
    forget_person_again,
)
from app.platform.contracts.events.identity import UserDeleted
from app.platform.di import PlatformProvider
from app.platform.kernel.errors import ExternalServiceError, RateLimitedError
from app.platform.kernel.ids import UserId, new_id
from app.platform.queue.dispatcher import EventDispatcher
from app.platform.queue.port import TaskRef
from app.platform.queue.tasks import TASKS
from app.platform.settings import Settings

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
PROJECT = 4242


def persons(handler: Any) -> PostHogPersons:
    transport = httpx.MockTransport(handler)
    return PostHogPersons(
        client_for("https://eu.i.posthog.com", PROJECT, "phx_test", transport=transport)
    )


def bulk_deleted(found: int, errors: list[dict[str, str]] | None = None) -> httpx.Response:
    return httpx.Response(
        202,
        json={
            "persons_found": found,
            "persons_deleted": 0,
            "persons_queued_for_deletion": found,
            "events_queued_for_deletion": found > 0,
            "recordings_queued_for_deletion": False,
            "deletion_errors": errors or [],
        },
    )


async def test_found_person_is_deleted_with_events() -> None:
    """Один запрос bulk_delete по distinct_id capture (внутренний UUID) — с событиями, по
    personal API key в адрес REST API, а не приёма событий."""
    requests: list[httpx.Request] = []
    user_id = new_id()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return bulk_deleted(found=1)

    with capture_logs() as logs:
        await persons(handler).forget(user_id)

    [request] = requests
    assert request.method == "POST"
    assert str(request.url) == f"https://eu.posthog.com/api/projects/{PROJECT}/persons/bulk_delete/"
    assert request.headers["Authorization"] == "Bearer phx_test"
    assert json.loads(request.content) == {"distinct_ids": [str(user_id)], "delete_events": True}
    [entry] = [e for e in logs if e["event"] == "analytics_person_forgotten"]
    assert entry["persons_found"] == 1
    assert entry["user_id"] == str(user_id)


async def test_missing_person_is_done() -> None:
    """Повтор задачи или аккаунт без событий в PostHog: персоны нет — готово, не ошибка."""
    await persons(lambda _: bulk_deleted(found=0)).forget(new_id())


async def test_server_errors_are_retried() -> None:
    for status in (500, 502, 503, 408):
        with pytest.raises(ExternalServiceError):
            await persons(lambda _, s=status: httpx.Response(s)).forget(new_id())

    def offline(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    with pytest.raises(ExternalServiceError):
        await persons(offline).forget(new_id())


async def test_deletion_errors_in_202_are_retried_not_done() -> None:
    """PostHog принял запрос (202), но удалил не всё: `deletion_errors` — повтор задачи, а не
    «готово»; содержимое ошибок (в нём distinct_id) в лог не идёт."""
    user_id = new_id()
    errors = [{"distinct_id": str(user_id), "error": "ClickHouse timeout"}]

    with capture_logs() as logs, pytest.raises(ExternalServiceError) as caught:
        await persons(lambda _: bulk_deleted(found=1, errors=errors)).forget(user_id)

    assert caught.value.params == {"service": "posthog", "reason": "deletion_errors"}
    assert [(e["event"], e["errors"]) for e in logs] == [
        ("analytics_person_deletion_incomplete", 1)
    ]
    assert "ClickHouse" not in repr(logs)


class _Job:
    def __init__(self, attempts: int) -> None:
        self.attempts = attempts


def test_forget_retries_are_bounded_then_the_task_fails() -> None:
    """Повторы ограничены: последний запуск — без решения о повторе, задача падает в failed
    (ERROR-лог Procrastinate → Sentry), а не крутится вечно."""
    retry = ExternalServiceError(service="posthog", reason="deletion_errors")
    waits = [
        FORGET_RETRY.get_retry_decision(exception=retry, job=_Job(n))  # type: ignore[arg-type]
        for n in range(FORGET_RETRY.max_attempts)
    ]
    assert all(w is not None for w in waits[:-1])
    assert waits[-1] is None


async def test_rate_limit_waits_retry_after() -> None:
    limited = persons(lambda _: httpx.Response(429, headers={"Retry-After": "17"}))

    with pytest.raises(RateLimitedError) as caught:
        await limited.forget(new_id())
    assert caught.value.retry_after == 17


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_rejection_is_loud_not_done(status: int) -> None:
    """Ключ без `person:write` или неверный проект: молча считать персону удалённой нельзя —
    ошибка без ключа в тексте, задача упадёт (Sentry) и останется в очереди."""
    with pytest.raises(PostHogPersonsError) as caught:
        await persons(lambda _: httpx.Response(status, json={"detail": "nope"})).forget(new_id())
    assert "phx_test" not in str(caught.value)


async def test_without_keys_deletion_is_noop_with_warning() -> None:
    """PostHog включён, а personal key или id проекта нет (K32a): запроса нет, предупреждение;
    без PostHog удалять нечего — только info."""
    user_id = new_id()

    with capture_logs() as logs:
        await NoPersonDeletion(capturing=True).forget(user_id)
        await NoPersonDeletion(capturing=False).forget(user_id)

    assert [(e["log_level"], e["event"]) for e in logs] == [
        ("warning", "analytics_person_not_forgotten"),
        ("info", "analytics_person_not_forgotten"),
    ]
    assert "ANALYTICS_POSTHOG_PERSONAL_API_KEY" in logs[0]["reason"]


async def resolve_deletion(settings: Settings) -> object:
    container = make_async_container(PlatformProvider(), context={Settings: settings})
    try:
        return await container.get(PersonDeletion)
    finally:
        await container.close()


async def test_di_deletes_only_with_posthog_and_personal_key(
    offline_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Без PostHog удалять нечего; PostHog без personal key и id проекта — no-op; с ними — API."""
    assert isinstance(await resolve_deletion(offline_settings), NoPersonDeletion)
    monkeypatch.setenv("ANALYTICS_POSTHOG_API_KEY", "phc_test")
    monkeypatch.setenv("ANALYTICS_POSTHOG_PERSONAL_API_KEY", "phx_test")
    assert isinstance(await resolve_deletion(Settings(env_file=None)), NoPersonDeletion)
    monkeypatch.setenv("ANALYTICS_POSTHOG_PROJECT_ID", str(PROJECT))
    assert isinstance(await resolve_deletion(Settings(env_file=None)), PostHogPersons)


class FakePersons:
    def __init__(self) -> None:
        self.forgotten: list[UUID] = []

    async def forget(self, user_id: UUID) -> None:
        self.forgotten.append(user_id)


async def test_user_deleted_forgets_person() -> None:
    fake = FakePersons()
    user_id = UserId(new_id())
    event = UserDeleted(user_id=user_id, occurred_at=NOW)

    await forget_person(event, fake)
    await forget_person_again(event, fake)

    assert fake.forgotten == [user_id, user_id]
    assert (UserDeleted, FORGET_PERSON) in TASKS.subscriptions
    assert (UserDeleted, FORGET_PERSON_AGAIN) in TASKS.subscriptions


async def test_second_pass_is_scheduled_a_day_after_deletion() -> None:
    """Событие, принятое PostHog после первого прохода, заводит персону заново: при commit
    удаления ставятся оба прохода — сразу и через сутки (повтор идемпотентен)."""
    calls: list[tuple[str, datetime | None]] = []

    class RecordingQueue:
        async def enqueue(
            self,
            task: TaskRef[object],
            payload: object,
            *,
            dedup_key: str | None = None,
            not_before: datetime | None = None,
            priority: int = 0,
        ) -> None:
            calls.append((task.name, not_before))

    registry = TASKS.event_registry()
    await EventDispatcher(registry, RecordingQueue()).enqueue(
        [UserDeleted(user_id=UserId(new_id()), occurred_at=NOW)]
    )

    forget = dict(c for c in calls if c[0].startswith("analytics."))
    assert forget == {
        "analytics.forget_person": None,
        "analytics.forget_person_again": NOW + timedelta(hours=24),
    }


# --- после удаления события не уходят ------------------------------------------------------


class FakeDeletedUsers:
    def __init__(self, *deleted: UUID) -> None:
        self._deleted = frozenset(deleted)

    async def deleted(self, user_ids: Collection[UUID]) -> frozenset[UUID]:
        return self._deleted & frozenset(user_ids)


def event_of(user_id: UUID) -> AnalyticsEvent:
    return analytics_event(
        EventName.WRITE_ACCESS_GRANTED,
        user_id=user_id,
        occurred_at=NOW,
        source_event_id=new_id(),
        via="bot_start",
    )


async def test_events_of_deleted_users_are_not_sent_to_posthog() -> None:
    """Отмена сделки и закрытие заявок после UserDeleted несут id удалённого: такое событие
    завело бы в PostHog персону заново."""
    gone, alive = new_id(), new_id()
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content)["distinct_id"])
        return httpx.Response(200, json={"status": 1})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    analytics = PostHogAnalytics(
        client,
        api_key=SecretStr("phc_test"),
        host="https://eu.i.posthog.com",
        environment="dev",
        deleted=FakeDeletedUsers(gone),
    )

    with capture_logs() as logs:
        await analytics.capture(event_of(gone))
        await analytics.capture(event_of(alive))

    assert sent == [str(alive)]
    assert [e["reason"] for e in logs if e["event"] == "analytics_event_skipped"] == [
        "user_deleted"
    ]


async def test_logging_fake_also_skips_deleted_users() -> None:
    gone, alive = new_id(), new_id()
    fake = LoggingAnalytics(deleted=FakeDeletedUsers(gone))

    await fake.capture(event_of(gone))
    await fake.capture(event_of(alive))

    assert [e.distinct_id for e in fake.captured] == [alive]
