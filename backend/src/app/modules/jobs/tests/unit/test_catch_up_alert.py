"""Досыл новой подписке (`jobs.catch_up_alert`, DEVELOPMENT_PLAN 5.7): открытые заявки последних
трёх суток уходят обычными карточками в лимит частоты, дальше — в подборку; заявки
заблокированных, свои отклики и скрытые — нет; выключенная подписка, санкция на отклик и повтор
задачи — ничего."""

from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from typing import Any, Self, cast

import pytest

from app.modules.identity.api import Action, IdentityApi
from app.modules.jobs.application.alerts import (
    CATCH_UP_LIMIT,
    CATCH_UP_WINDOW,
    INSTANT_PER_HOUR,
    AlertMatch,
    JobCandidate,
    RecentCards,
)
from app.modules.jobs.application.ports import AlertMatches, JobAlerts, JobQueries
from app.modules.jobs.application.use_cases.catch_up_alert import (
    CatchUpAlert,
    CatchUpAlertCommand,
)
from app.modules.jobs.domain.alert import AlertCriteria, AlertDelivery, AlertId, JobAlert
from app.modules.jobs.domain.job import JobId
from app.platform.contracts.notices import NOTIFY_JOB_MATCHED, JobMatchNotice
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import CategoryId, CityId, UserId, new_id
from app.platform.queue.port import JobQueue, TaskRef
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 12, 10, 0, tzinfo=UTC)
ANA = UserId(new_id())
INSTANT, DIGEST = AlertDelivery.INSTANT, AlertDelivery.DIGEST


def alert(delivery: AlertDelivery = INSTANT, *, active: bool = True) -> JobAlert:
    return JobAlert(
        id=AlertId(new_id()),
        user_id=ANA,
        criteria=AlertCriteria(category_ids=(CategoryId(1),), city_id=CityId(1)),
        delivery=delivery,
        is_active=active,
        paused_until=None,
        created_at=NOW,
        updated_at=NOW,
    )


def job(client: UserId | None = None, distance: float | None = None) -> JobCandidate:
    return JobCandidate(
        job_id=JobId(new_id()), client_id=client or UserId(new_id()), distance_m=distance
    )


class Transactions:
    def __init__(self) -> None:
        self.opened = 0

    async def __aenter__(self) -> Self:
        self.opened += 1
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class Alerts:
    def __init__(self, found: JobAlert | None) -> None:
        self.found = found

    async def get(self, alert_id: AlertId) -> JobAlert | None:
        return self.found if self.found is not None and self.found.id == alert_id else None


class Matches:
    """Совпадения: кандидаты досыла, уже полученные карточки, запись пар «заявка — человек»."""

    def __init__(self, candidates: list[JobCandidate], *, recent: RecentCards | None) -> None:
        self.candidates, self.recent = candidates, recent
        self.asked: list[tuple[AlertId, datetime, datetime, datetime, int]] = []
        self.recorded: dict[JobId, AlertMatch] = {}
        self.notified: dict[JobId, int] = {}

    async def recent_jobs(
        self, alert_id: AlertId, *, since: datetime, until: datetime, now: datetime, limit: int
    ) -> list[JobCandidate]:
        self.asked.append((alert_id, since, until, now, limit))
        return list(self.candidates)

    async def recent_cards(
        self, user_ids: Collection[UserId], now: datetime
    ) -> dict[UserId, RecentCards]:
        return {ANA: self.recent} if self.recent is not None else {}

    async def record(
        self, job_id: JobId, matches: Collection[AlertMatch], now: datetime
    ) -> list[AlertMatch]:
        if job_id in self.recorded:
            return []
        [match] = matches
        self.recorded[job_id] = match
        return [match]

    async def add_notified(self, job_id: JobId, count: int) -> None:
        self.notified[job_id] = self.notified.get(job_id, 0) + count


class Queries:
    def __init__(self, skipped: Collection[JobId] = ()) -> None:
        self.skipped_jobs = set(skipped)

    async def skipped(self, job_ids: Collection[JobId], user_id: UserId) -> set[JobId]:
        return self.skipped_jobs & set(job_ids)


class Identity:
    def __init__(self, *, blocked: Collection[UserId] = (), barred: bool = False) -> None:
        self.blocked, self.is_barred = frozenset(blocked), barred

    async def barred(self, user_ids: Collection[UserId], action: Action) -> frozenset[UserId]:
        assert action is Action.RESPOND
        return frozenset(user_ids) if self.is_barred else frozenset()

    async def blocked_ids(self, user_id: UserId) -> frozenset[UserId]:
        return self.blocked


class Queue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[TaskRef[Any], Any, str | None, int]] = []

    async def enqueue(
        self,
        task: TaskRef[Any],
        payload: Any,
        *,
        dedup_key: str | None = None,
        not_before: datetime | None = None,
        priority: int = 0,
    ) -> None:
        self.enqueued.append((task, payload, dedup_key, priority))


def use_case(
    found: JobAlert | None,
    candidates: list[JobCandidate],
    *,
    recent: RecentCards | None = None,
    skipped: Collection[JobId] = (),
    identity: Identity | None = None,
) -> tuple[CatchUpAlert, Transactions, Matches, Queue]:
    uow, matches, queue = Transactions(), Matches(candidates, recent=recent), Queue()
    catch_up = CatchUpAlert(
        cast(UnitOfWork, uow),
        cast(JobAlerts, Alerts(found)),
        cast(AlertMatches, matches),
        cast(JobQueries, Queries(skipped)),
        cast(IdentityApi, identity or Identity()),
        cast(JobQueue, queue),
        FakeClock(NOW),
    )
    return catch_up, uow, matches, queue


async def test_open_jobs_of_last_days_go_as_cards_then_digest() -> None:
    mine = alert()
    jobs = [job(distance=float(i * 1000)) for i in range(4)]
    catch_up, uow, matches, queue = use_case(
        mine, jobs, recent=RecentCards(hour=INSTANT_PER_HOUR - 3, day=5)
    )

    sent = await catch_up(CatchUpAlertCommand(alert_id=mine.id))

    assert sent == 4
    assert uow.opened == 1
    assert matches.asked == [(mine.id, NOW - CATCH_UP_WINDOW, NOW, NOW, CATCH_UP_LIMIT)]
    assert [matches.recorded[item.job_id].delivery for item in jobs] == [
        INSTANT,
        INSTANT,
        INSTANT,
        DIGEST,
    ]
    assert matches.notified == {item.job_id: 1 for item in jobs}
    # карточки — только «сразу», как у jobs.match_alerts: тот же ключ и приоритет
    assert [(task, payload, key, priority) for task, payload, key, priority in queue.enqueued] == [
        (
            NOTIFY_JOB_MATCHED,
            JobMatchNotice(
                job_id=item.job_id, user_id=ANA, alert_id=mine.id, distance_m=max(100, i * 1000)
            ),
            f"job.matched:{item.job_id}:{ANA}",
            -1,
        )
        for i, item in enumerate(jobs[:3])
    ]


async def test_blocked_clients_own_responses_and_hidden_jobs_are_left_out() -> None:
    mine = alert()
    enemy = UserId(new_id())
    wanted, blocked, answered = job(), job(enemy), job()
    catch_up, _, matches, queue = use_case(
        mine,
        [wanted, blocked, answered],
        skipped=[answered.job_id],
        identity=Identity(blocked=[enemy]),
    )

    assert await catch_up(CatchUpAlertCommand(alert_id=mine.id)) == 1
    assert list(matches.recorded) == [wanted.job_id]
    assert len(queue.enqueued) == 1


async def test_digest_alert_waits_for_its_digest() -> None:
    mine = alert(DIGEST)
    catch_up, _, matches, queue = use_case(mine, [job(), job()])

    assert await catch_up(CatchUpAlertCommand(alert_id=mine.id)) == 2
    assert {match.delivery for match in matches.recorded.values()} == {DIGEST}
    assert queue.enqueued == []


@pytest.mark.parametrize(
    ("found", "identity"),
    [
        (None, Identity()),
        (alert(active=False), Identity()),
        (alert(), Identity(barred=True)),
    ],
)
async def test_missing_or_off_alert_and_barred_subscriber_get_nothing(
    found: JobAlert | None, identity: Identity
) -> None:
    catch_up, uow, matches, _ = use_case(found, [job()], identity=identity)

    assert await catch_up(CatchUpAlertCommand(alert_id=AlertId(new_id()))) == 0
    assert (uow.opened, matches.asked, matches.recorded) == (0, [], {})


async def test_paused_alert_and_empty_window_cost_no_transaction() -> None:
    paused = alert()
    paused = JobAlert(
        **{
            field: getattr(paused, field)
            for field in ("id", "user_id", "criteria", "delivery", "is_active", "created_at")
        },
        paused_until=NOW + timedelta(days=1),
        updated_at=NOW,
    )
    catch_up, uow, _, _ = use_case(paused, [job()])
    assert await catch_up(CatchUpAlertCommand(alert_id=paused.id)) == 0

    fresh = alert()
    catch_up, uow, _, _ = use_case(fresh, [])
    assert await catch_up(CatchUpAlertCommand(alert_id=fresh.id)) == 0
    assert uow.opened == 0


async def test_repeated_task_sends_no_second_card() -> None:
    mine = alert()
    first = job()
    catch_up, _, matches, queue = use_case(mine, [first])
    await catch_up(CatchUpAlertCommand(alert_id=mine.id))

    assert await catch_up(CatchUpAlertCommand(alert_id=mine.id)) == 0
    assert (matches.notified[first.job_id], len(queue.enqueued)) == (1, 1)
