"""Сроки сделки (DEVELOPMENT_PLAN 6.1b; ARCHITECTURE §12.3): напоминание за 2 ч до времени,
«Работа выполнена?» через 3 ч после него (без времени — через сутки после договорённости),
автозавершение через 72 ч после отметки одной стороны, истечение «Договорились» за 72 ч.
Каждое — один раз и только у идущей сделки."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.modules.deals.domain.deal import (
    Deal,
    DealCancelReason,
    DealPriceType,
    DealStatus,
    DealTerms,
)
from app.platform.contracts.events.deals import (
    DealCancelled,
    DealCompleted,
    DealCompletionDue,
    DealReminderDue,
)
from app.platform.kernel.ids import DealId, UserId, new_id

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
CLIENT, PERFORMER = UserId(new_id()), UserId(new_id())


def deal(*, at: datetime | None = None) -> Deal:
    created = Deal.agree_from_response(
        deal_id=DealId(new_id()),
        client_id=CLIENT,
        performer_id=PERFORMER,
        profile_id=None,
        job_id=new_id(),
        response_id=new_id(),
        terms=DealTerms(
            title="Повесить люстру",
            price_type=DealPriceType.FIXED,
            agreed_price=350_000,
            scheduled_at=at,
        ),
        now=NOW,
    )
    created.pull_events()
    return created


def test_reminder_two_hours_before_once() -> None:
    work = deal(at=NOW + timedelta(hours=5))

    assert not work.remind(now=NOW)  # ещё рано
    assert work.remind(now=NOW + timedelta(hours=3, minutes=10))
    assert not work.remind(now=NOW + timedelta(hours=4))  # уже напоминали

    [event] = work.pull_events()
    assert isinstance(event, DealReminderDue)
    assert event.scheduled_at == NOW + timedelta(hours=5)
    assert not deal(at=None).remind(now=NOW)  # время не договорено
    late = deal(at=NOW + timedelta(hours=1))
    assert not late.remind(now=NOW + timedelta(hours=2))  # время уже прошло


def test_completion_prompt_after_the_time_asks_who_has_not_marked() -> None:
    work = deal(at=NOW + timedelta(hours=1))
    work.complete(actor_id=PERFORMER, now=NOW + timedelta(hours=2))

    assert not work.prompt_completion(now=NOW + timedelta(hours=3, minutes=59))
    assert work.prompt_completion(now=NOW + timedelta(hours=4))
    assert not work.prompt_completion(now=NOW + timedelta(hours=5))  # один раз

    [event] = work.pull_events()
    assert isinstance(event, DealCompletionDue)
    assert (event.ask_client, event.ask_performer) == (True, False)


def test_completion_prompt_without_time_a_day_after_agreement() -> None:
    work = deal(at=None)

    assert work.completion_due_at == NOW + timedelta(hours=24)
    assert not work.prompt_completion(now=NOW + timedelta(hours=23))
    assert work.prompt_completion(now=NOW + timedelta(hours=24))


def test_silent_party_for_three_days_completes_the_deal() -> None:
    work = deal()
    work.complete(actor_id=CLIENT, now=NOW)

    assert not work.auto_complete(now=NOW + timedelta(hours=71))
    assert work.auto_complete(now=NOW + timedelta(hours=72))

    assert (work.status, work.completed_at) == (DealStatus.COMPLETED, NOW + timedelta(hours=72))
    [event] = work.pull_events()
    assert isinstance(event, DealCompleted)
    assert event.auto
    [_, change] = work.pull_history()
    assert (change.actor_id, change.reason) == (None, "auto")


def test_auto_complete_needs_exactly_one_mark() -> None:
    assert not deal().auto_complete(now=NOW + timedelta(days=30))  # никто не отметил


def test_unanswered_proposal_expires() -> None:
    proposal = Deal.propose(
        deal_id=DealId(new_id()),
        client_id=CLIENT,
        performer_id=PERFORMER,
        proposed_by=CLIENT,
        profile_id=None,
        conversation_id=UUID(int=1),
        terms=DealTerms(title="Уборка"),
        now=NOW,
    )

    assert not proposal.expire_proposal(now=NOW + timedelta(hours=71))
    assert proposal.expire_proposal(now=NOW + timedelta(hours=72))

    assert (proposal.status, proposal.cancel_reason) == (
        DealStatus.CANCELLED,
        DealCancelReason.EXPIRED,
    )
    [event] = proposal.pull_events()
    assert isinstance(event, DealCancelled)
    assert event.cancelled_by == "system"
    assert not deal().expire_proposal(now=NOW + timedelta(days=5))  # не предложение


def test_finished_deal_has_no_deadlines() -> None:
    work = deal(at=NOW + timedelta(hours=1))
    work.cancel(actor_id=CLIENT, reason=DealCancelReason.OTHER, now=NOW)

    later = NOW + timedelta(days=5)
    assert not work.remind(now=NOW)
    assert not work.prompt_completion(now=later)
    assert not work.auto_complete(now=later)
