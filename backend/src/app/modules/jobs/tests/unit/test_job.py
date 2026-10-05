"""Заявка (DEVELOPMENT_PLAN 5.1; ARCHITECTURE §7.9): жизненный цикл, срок жизни, продления,
напоминание о сроке, правки, закрытие, политики владения."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.jobs.domain.job import (
    Budget,
    BudgetType,
    BudgetUnit,
    CloseReason,
    Job,
    JobStatus,
    Urgency,
    lifetime,
)
from app.modules.jobs.domain.policies import ensure_owner, ensure_visible
from app.modules.jobs.errors import (
    InvalidJobError,
    JobExtendLimitError,
    JobNotFoundError,
    JobNotOpenError,
)
from app.modules.jobs.tests.builders import (
    CLIENT,
    ELECTRICAL,
    NOW,
    content,
    published,
    submitted,
)
from app.platform.contracts.events.jobs import (
    JobClosed,
    JobExpired,
    JobExpiring,
    JobPublished,
    JobSubmitted,
    JobUpdated,
)
from app.platform.kernel.errors import StaleVersionError
from app.platform.kernel.ids import UserId, new_id

pytestmark = pytest.mark.unit

STRANGER = UserId(new_id())


def statuses(job: Job) -> list[tuple[str, str]]:
    return [(change.from_.value, change.to.value) for change, _ in job.pull_history()]


def test_new_job_waits_for_moderation_right_away() -> None:
    job = Job.submit(
        job_id=submitted().id, client_id=CLIENT, content=content(), max_responses=5, now=NOW
    )

    assert job.status is JobStatus.PENDING_MODERATION
    assert statuses(job) == [("draft", "pending_moderation")]
    assert [type(e) for e in job.pull_events()] == [JobSubmitted]


def test_moderation_publishes_with_the_lifetime_of_its_urgency() -> None:
    job = submitted(urgency=Urgency.ASAP)

    assert job.approve(version=None, now=NOW)

    assert (job.status, job.published_at, job.expires_at) == (
        JobStatus.PUBLISHED,
        NOW,
        NOW + timedelta(hours=24),
    )
    event = job.pull_events()[0]
    assert isinstance(event, JobPublished)
    assert not event.republished


def test_stale_moderation_version_publishes_nothing() -> None:
    job = submitted()

    assert not job.approve(version=job.revision + 1, now=NOW)
    assert job.status is JobStatus.PENDING_MODERATION


def test_moderator_approves_only_the_revision_the_card_showed() -> None:
    """ADV-11: клиент поправил заявку после карточки — одобрение прежней редакции ничего не
    публикует; правленую публикует только решение о ней."""
    job = submitted()
    seen = job.revision

    job.edit(content(title="Звоните мне напрямую"), now=NOW)

    assert job.revision == seen + 1
    assert not job.approve(version=seen, now=NOW)
    assert job.approve(version=job.revision, now=NOW)


def test_if_match_survives_moderation_transitions() -> None:
    """ADV-07: If-Match сверяет редакцию содержимого — автопубликация и решения модерации её не
    меняют, повтор той же правки — тоже; ложного 412 после своей же правки нет."""
    job = submitted()
    revision = job.revision

    job.approve(version=revision, now=NOW)  # автопроверка опубликовала
    job.ensure_revision(revision)
    job.edit(content(), now=NOW)  # то же содержимое — не новая редакция
    job.ensure_revision(revision)
    job.edit(content(title="Повесить две люстры"), now=NOW)  # снова на проверку
    job.approve(version=job.revision, now=NOW)
    job.ensure_revision(revision + 1)
    with pytest.raises(StaleVersionError):
        job.ensure_revision(revision)  # правка из другого места — 412 как раньше


@pytest.mark.parametrize(
    ("urgency", "now", "expires"),
    [
        (Urgency.ASAP, NOW, NOW + timedelta(hours=24)),
        (Urgency.THIS_WEEK, NOW, NOW + timedelta(days=7)),
        (Urgency.FLEXIBLE, NOW, NOW + timedelta(days=30)),
        # «сегодня» — до 23:59 по Белграду (UTC+2) и ещё 6 часов
        (Urgency.TODAY, NOW, datetime(2026, 10, 3, 3, 59, tzinfo=UTC)),
        (
            Urgency.TODAY,
            datetime(2026, 10, 2, 22, 30, tzinfo=UTC),
            datetime(2026, 10, 4, 3, 59, tzinfo=UTC),
        ),
    ],
)
def test_lifetime_follows_urgency(urgency: Urgency, now: datetime, expires: datetime) -> None:
    assert lifetime(urgency, now) == expires


def test_extension_three_times_then_conflict() -> None:
    job = published()
    later = NOW + timedelta(days=1)

    for _ in range(3):
        job.extend(now=later)

    # каждый раз — ещё неделя к сроку, который не вышел
    assert (job.extensions_count, job.expires_at) == (3, NOW + timedelta(days=28))
    with pytest.raises(JobExtendLimitError):
        job.extend(now=later)


def test_extending_a_today_job_the_same_evening_adds_a_day() -> None:
    job = published(urgency=Urgency.TODAY)
    expires = job.expires_at
    assert expires is not None

    job.extend(now=NOW + timedelta(hours=2))

    assert job.expires_at == expires + timedelta(days=1)


def test_expired_job_is_republished_by_extension() -> None:
    job = published()
    assert not job.expire(now=NOW)
    later = NOW + timedelta(days=8)
    assert job.expire(now=later)
    assert isinstance(job.pull_events()[-1], JobExpired)

    job.extend(now=later)

    assert (job.status, job.expires_at) == (JobStatus.PUBLISHED, later + timedelta(days=7))
    event = job.pull_events()[-1]
    assert isinstance(event, JobPublished)
    assert event.republished


def test_substantive_edit_sends_a_published_job_back_to_moderation() -> None:
    job = published()

    assert not job.edit(content(urgency=Urgency.ASAP), now=NOW)
    assert statuses(job) == []
    assert job.edit(content(title="Повесить две люстры"), now=NOW)
    assert statuses(job) == [("published", "pending_moderation")]
    assert all(isinstance(e, JobUpdated) for e in job.pull_events())


def test_rejected_job_goes_back_to_moderation_after_any_fix() -> None:
    job = submitted()
    assert job.reject(reason_code="contact_leak", now=NOW)
    assert (job.status, job.moderation_note) == (JobStatus.REJECTED, "contact_leak")

    assert job.edit(content(urgency=Urgency.ASAP), now=NOW)

    assert (job.status, job.moderation_note) == (JobStatus.PENDING_MODERATION, None)


def test_moderation_removes_a_published_job() -> None:
    job = published()

    assert job.reject(reason_code="prepayment_scam", now=NOW)

    assert (job.status, job.close_reason) == (JobStatus.REMOVED, CloseReason.REMOVED)
    event = job.pull_events()[-1]
    assert isinstance(event, JobClosed)
    assert event.reason == "removed"


def test_client_closes_with_own_reasons_only() -> None:
    job = published()
    with pytest.raises(InvalidJobError):
        job.close(CloseReason.EXPIRED, now=NOW)

    job.close(CloseReason.HIRED_ELSEWHERE, now=NOW)

    assert (job.status, job.close_reason, job.closed_at) == (
        JobStatus.CLOSED,
        CloseReason.HIRED_ELSEWHERE,
        NOW,
    )
    with pytest.raises(JobNotOpenError):
        job.extend(now=NOW)
    with pytest.raises(JobNotOpenError):
        job.edit(content(), now=NOW)


def test_deleted_job_is_closed_and_gone() -> None:
    job = published()

    job.delete(now=NOW)

    assert (job.status, job.deleted_at) == (JobStatus.CLOSED, NOW)
    with pytest.raises(JobNotFoundError):
        ensure_visible(job, CLIENT)


def test_strangers_see_only_published_and_never_act_as_owner() -> None:
    pending, live = submitted(), published()

    with pytest.raises(JobNotFoundError):
        ensure_visible(pending, STRANGER)
    ensure_visible(pending, CLIENT)
    ensure_visible(live, None)
    with pytest.raises(JobNotFoundError):
        ensure_owner(live, STRANGER)


@pytest.mark.parametrize(
    ("budget", "field"),
    [
        ({"type": BudgetType.FIXED}, "budget_min"),
        ({"type": BudgetType.FIXED, "min": 100, "max": 200}, "budget_max"),
        ({"type": BudgetType.RANGE, "min": 300, "max": 200}, "budget_max"),
        ({"type": BudgetType.NEGOTIABLE, "min": 100}, "budget"),
        ({"type": BudgetType.FIXED, "min": -5}, "budget"),
    ],
)
def test_budget_rules(budget: dict[str, object], field: str) -> None:
    with pytest.raises(InvalidJobError) as error:
        Budget(**budget)  # type: ignore[arg-type]
    assert error.value.params["field"] == field


def test_title_and_dates_are_checked() -> None:
    with pytest.raises(InvalidJobError):
        content(title="Ой")
    with pytest.raises(InvalidJobError):
        content(preferred_from=NOW, preferred_to=NOW - timedelta(hours=1))
    assert content(title="  Повесить полку  ").title == "Повесить полку"
    assert Budget(type=BudgetType.RANGE, min=100, unit=BudgetUnit.HOUR).max is None


@pytest.mark.parametrize(
    ("preferred_from", "preferred_to", "field"),
    [
        (NOW.replace(tzinfo=None), NOW, "preferred_from"),
        (NOW, NOW.replace(tzinfo=None), "preferred_to"),
        (NOW.replace(tzinfo=None), None, "preferred_from"),
        (None, NOW.replace(tzinfo=None), "preferred_to"),
        (NOW.replace(tzinfo=None), NOW.replace(tzinfo=None), "preferred_from"),
    ],
)
def test_preferred_dates_require_timezone(
    preferred_from: datetime | None, preferred_to: datetime | None, field: str
) -> None:
    with pytest.raises(InvalidJobError) as error:
        content(preferred_from=preferred_from, preferred_to=preferred_to)

    assert error.value.params == {"field": field, "reason": "timezone_required"}


@pytest.mark.parametrize(
    ("preferred_from", "preferred_to"),
    [
        (None, None),
        (NOW, None),
        (None, NOW),
        (NOW, datetime.fromisoformat("2026-10-02T12:00:00+02:00")),
    ],
)
def test_preferred_dates_accept_timezone_and_optional_bounds(
    preferred_from: datetime | None, preferred_to: datetime | None
) -> None:
    job_content = content(preferred_from=preferred_from, preferred_to=preferred_to)

    assert job_content.preferred_from == preferred_from
    assert job_content.preferred_to == preferred_to


def test_preferred_dates_are_ordered_by_instant() -> None:
    with pytest.raises(InvalidJobError) as error:
        content(
            preferred_from=NOW,
            preferred_to=datetime.fromisoformat("2026-10-02T11:00:00+02:00"),
        )

    assert error.value.params == {"field": "preferred_to", "reason": "before_from"}


def test_reminder_comes_once_per_term_two_hours_before_the_end() -> None:
    job = published(urgency=Urgency.ASAP)
    expires = job.expires_at
    assert expires is not None

    assert not job.remind_expiry(now=expires - timedelta(hours=3))
    assert job.remind_expiry(now=expires - timedelta(hours=2))
    assert not job.remind_expiry(now=expires - timedelta(hours=1))  # одно за срок

    event = job.pull_events()[-1]
    assert isinstance(event, JobExpiring)
    assert (event.job_id, event.expires_at) == (job.id, expires)
    job.extend(now=expires - timedelta(hours=1))  # новый срок — новое напоминание
    renewed = job.expires_at
    assert renewed is not None
    assert job.expiry_reminded_at is None
    assert job.remind_expiry(now=renewed - timedelta(minutes=30))


def test_no_reminder_once_the_term_is_over_or_the_job_closed() -> None:
    job = published()
    expires = job.expires_at
    assert expires is not None

    assert not job.remind_expiry(now=expires + timedelta(minutes=1))
    job.close(CloseReason.NOT_NEEDED, now=NOW)
    assert not job.remind_expiry(now=expires - timedelta(hours=1))


def test_events_carry_category_city_and_urgency() -> None:
    job = submitted(urgency=Urgency.TODAY)
    assert job.approve(version=None, now=NOW)
    published_event = job.pull_events()[-1]
    job.close(CloseReason.HIRED_HERE, now=NOW)
    closed_event = job.pull_events()[-1]

    assert isinstance(published_event, JobPublished)
    assert (published_event.urgency, published_event.category_id) == ("today", ELECTRICAL)
    assert isinstance(closed_event, JobClosed)
    assert (closed_event.reason, closed_event.category_id, closed_event.city_id) == (
        "hired_here",
        ELECTRICAL,
        job.content.place.city_id,
    )
