"""Сделка (DEVELOPMENT_PLAN 6.1a; ARCHITECTURE §7.9): state machine — выбор отклика, «Договорились»
и подтверждение, «Работа выполнена» с двух сторон, отмена стороной и системой."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from app.modules.deals.domain.deal import (
    MAX_TITLE,
    ActorKind,
    Deal,
    DealCancelReason,
    DealOrigin,
    DealPriceType,
    DealRole,
    DealStatus,
    DealTerms,
)
from app.modules.deals.errors import (
    DealMarkedDoneError,
    DealNotActiveError,
    DealNotFoundError,
    InvalidDealError,
)
from app.platform.contracts.events.deals import (
    DealAgreed,
    DealCancelled,
    DealCompleted,
    DealMarkedDone,
    DealProposed,
)
from app.platform.kernel.ids import CategoryId, DealId, UserId, new_id

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=5)
CLIENT = UserId(new_id())
PERFORMER = UserId(new_id())
STRANGER = UserId(new_id())
JOB_ID, RESPONSE_ID = new_id(), new_id()


def terms(**fields: Any) -> DealTerms:
    values: dict[str, Any] = {
        "title": "Повесить люстру",
        "category_id": CategoryId(5),
        "price_type": DealPriceType.FIXED,
        "agreed_price": 350_000,
    }
    values.update(fields)
    return DealTerms(**values)


def agreed() -> Deal:
    deal = Deal.agree_from_response(
        deal_id=DealId(new_id()),
        client_id=CLIENT,
        performer_id=PERFORMER,
        profile_id=None,
        job_id=JOB_ID,
        response_id=RESPONSE_ID,
        terms=terms(),
        now=NOW,
    )
    deal.pull_events()
    deal.pull_history()
    return deal


def proposed(by: UserId = PERFORMER) -> Deal:
    deal = Deal.propose(
        deal_id=DealId(new_id()),
        client_id=CLIENT,
        performer_id=PERFORMER,
        proposed_by=by,
        profile_id=None,
        conversation_id=UUID(int=7),
        terms=terms(),
        now=NOW,
    )
    deal.pull_events()
    deal.pull_history()
    return deal


def test_accepted_response_makes_an_agreed_deal() -> None:
    deal = Deal.agree_from_response(
        deal_id=DealId(new_id()),
        client_id=CLIENT,
        performer_id=PERFORMER,
        profile_id=None,
        job_id=JOB_ID,
        response_id=RESPONSE_ID,
        terms=terms(),
        now=NOW,
    )

    assert (deal.status, deal.origin, deal.agreed_at) == (
        DealStatus.AGREED,
        DealOrigin.JOB_RESPONSE,
        NOW,
    )
    [event] = deal.pull_events()
    assert isinstance(event, DealAgreed)
    assert (event.job_id, event.response_id, event.origin) == (
        JOB_ID,
        RESPONSE_ID,
        "job_response",
    )
    [change] = deal.pull_history()
    assert (change.from_, change.to, change.actor_id, change.actor_kind) == (
        None,
        DealStatus.AGREED,
        CLIENT,
        ActorKind.USER,
    )


def test_both_parties_mark_done_to_complete() -> None:
    deal = agreed()

    assert not deal.complete(actor_id=PERFORMER, now=NOW)
    assert not deal.complete(actor_id=PERFORMER, now=LATER)  # повтор — без изменений
    assert deal.performer_confirmed_at == NOW
    [marked] = deal.pull_events()  # клиента спросят «Работа выполнена?» сразу (7.3, B2)
    assert isinstance(marked, DealMarkedDone)
    assert (marked.deal_id, marked.marked_by, marked.occurred_at) == (deal.id, "performer", NOW)
    assert deal.complete(actor_id=CLIENT, now=LATER)

    assert (deal.status, deal.client_confirmed_at, deal.completed_at) == (
        DealStatus.COMPLETED,
        LATER,
        LATER,
    )
    [event] = deal.pull_events()
    assert isinstance(event, DealCompleted)
    assert (event.client_id, event.performer_id) == (CLIENT, PERFORMER)
    with pytest.raises(DealNotActiveError):
        deal.complete(actor_id=CLIENT, now=LATER)


@pytest.mark.parametrize(
    ("actor", "role"), [(CLIENT, DealRole.CLIENT), (PERFORMER, DealRole.PERFORMER)]
)
def test_party_cancels_with_a_reason(actor: UserId, role: DealRole) -> None:
    deal = agreed()

    deal.cancel(actor_id=actor, reason=DealCancelReason.PLANS_CHANGED, now=LATER)

    assert (deal.status, deal.cancelled_by, deal.cancel_reason, deal.cancelled_at) == (
        DealStatus.CANCELLED,
        actor,
        DealCancelReason.PLANS_CHANGED,
        LATER,
    )
    [event] = deal.pull_events()
    assert isinstance(event, DealCancelled)
    assert (event.cancelled_by, event.reason) == (role.value, "plans_changed")
    [change] = deal.pull_history()
    assert (change.from_, change.to, change.reason) == (
        DealStatus.AGREED,
        DealStatus.CANCELLED,
        "plans_changed",
    )


def test_cancel_rules() -> None:
    deal = agreed()
    with pytest.raises(InvalidDealError):  # системную причину сторона не выбирает
        deal.cancel(actor_id=CLIENT, reason=DealCancelReason.ACCOUNT_DELETED, now=LATER)
    with pytest.raises(DealNotFoundError):  # не участник — как нет сделки
        deal.cancel(actor_id=STRANGER, reason=DealCancelReason.OTHER, now=LATER)

    deal.complete(actor_id=CLIENT, now=LATER)
    deal.complete(actor_id=PERFORMER, now=LATER)
    with pytest.raises(DealNotActiveError):
        deal.cancel(actor_id=CLIENT, reason=DealCancelReason.OTHER, now=LATER)
    assert not deal.cancel_by_system(reason=DealCancelReason.ACCOUNT_DELETED, now=LATER)


@pytest.mark.parametrize(
    ("marker", "canceller"),
    [(CLIENT, PERFORMER), (PERFORMER, CLIENT), (CLIENT, CLIENT), (PERFORMER, PERFORMER)],
)
def test_no_party_cancel_after_work_marked_done(marker: UserId, canceller: UserId) -> None:
    """MU-8: после «Работа выполнена» одной стороны отмена стёрла бы отметку, а с ней отзыв
    клиента и спор. Остаются подтверждение, спор и автозавершение через 72 ч."""
    deal = agreed()
    deal.complete(actor_id=marker, now=NOW)
    deal.pull_events()

    with pytest.raises(DealMarkedDoneError):
        deal.cancel(actor_id=canceller, reason=DealCancelReason.PLANS_CHANGED, now=LATER)

    assert (deal.status, deal.cancelled_at, deal.pull_events()) == (DealStatus.AGREED, None, [])
    deal.open_dispute(actor_id=canceller, now=LATER)  # «Есть проблема» — доступна
    assert deal.status is DealStatus.DISPUTED


def test_marked_deal_still_completes_by_the_other_party() -> None:
    deal = agreed()
    deal.complete(actor_id=PERFORMER, now=NOW)

    assert deal.complete(actor_id=CLIENT, now=LATER)
    assert deal.status is DealStatus.COMPLETED


def test_system_cancels_an_agreed_deal() -> None:
    deal = agreed()

    assert deal.cancel_by_system(reason=DealCancelReason.ACCOUNT_DELETED, now=LATER)

    assert (deal.status, deal.cancelled_by) == (DealStatus.CANCELLED, None)
    [event] = deal.pull_events()
    assert isinstance(event, DealCancelled)
    assert event.cancelled_by == "system"
    [change] = deal.pull_history()
    assert change.actor_kind is ActorKind.SYSTEM


def test_proposal_is_announced_to_the_other_party() -> None:
    deal = Deal.propose(
        deal_id=DealId(new_id()),
        client_id=CLIENT,
        performer_id=PERFORMER,
        proposed_by=PERFORMER,
        profile_id=None,
        conversation_id=UUID(int=7),
        terms=terms(),
        now=NOW,
    )

    [event] = deal.pull_events()
    assert isinstance(event, DealProposed)
    assert (event.proposed_by, event.conversation_id) == (PERFORMER, UUID(int=7))


def test_proposal_waits_for_the_other_party() -> None:
    deal = proposed(by=PERFORMER)

    with pytest.raises(DealNotActiveError):  # предложивший сам не подтверждает
        deal.confirm(actor_id=PERFORMER, now=LATER)
    with pytest.raises(DealNotActiveError):  # «Работа выполнена» — только после согласия
        deal.complete(actor_id=CLIENT, now=LATER)
    deal.confirm(actor_id=CLIENT, now=LATER)

    assert (deal.status, deal.agreed_at) == (DealStatus.AGREED, LATER)
    [event] = deal.pull_events()
    assert isinstance(event, DealAgreed)
    assert event.origin == "chat"
    with pytest.raises(DealNotActiveError):
        deal.confirm(actor_id=CLIENT, now=LATER)


def test_proposal_can_be_declined_by_the_other_party() -> None:
    deal = proposed(by=CLIENT)

    deal.cancel(actor_id=PERFORMER, reason=DealCancelReason.NO_AGREEMENT, now=LATER)

    assert deal.status is DealStatus.CANCELLED


def test_only_a_waiting_proposal_can_be_declined() -> None:
    deal = proposed(by=PERFORMER)

    deal.decline(actor_id=CLIENT, now=LATER)

    assert (deal.status, deal.cancel_reason) == (
        DealStatus.CANCELLED,
        DealCancelReason.NO_AGREEMENT,
    )
    [event] = deal.pull_events()
    assert isinstance(event, DealCancelled)
    assert (event.cancelled_by, event.reason) == ("client", "no_agreement")
    agreed = proposed(by=PERFORMER)
    agreed.confirm(actor_id=CLIENT, now=LATER)
    with pytest.raises(DealNotActiveError):  # идущую сделку — только отменой с причиной
        agreed.decline(actor_id=CLIENT, now=LATER)
    with pytest.raises(DealNotFoundError):
        proposed().decline(actor_id=STRANGER, now=LATER)


def test_proposal_needs_a_party() -> None:
    with pytest.raises(InvalidDealError):
        proposed(by=STRANGER)


@pytest.mark.parametrize(
    "fields",
    [
        {"title": ""},
        {"title": "x" * (MAX_TITLE + 1)},
        {"agreed_price": 0},
        {"price_type": DealPriceType.NEGOTIABLE},
    ],
    ids=["empty-title", "long-title", "zero-price", "negotiable-with-amount"],
)
def test_invalid_terms(fields: dict[str, Any]) -> None:
    with pytest.raises(InvalidDealError):
        terms(**fields)


def test_parties_differ() -> None:
    with pytest.raises(InvalidDealError):
        Deal.agree_from_response(
            deal_id=DealId(new_id()),
            client_id=CLIENT,
            performer_id=CLIENT,
            profile_id=None,
            job_id=JOB_ID,
            response_id=RESPONSE_ID,
            terms=terms(),
            now=NOW,
        )


def test_role_of() -> None:
    deal = agreed()
    assert [deal.role_of(user) for user in (CLIENT, PERFORMER, STRANGER, None)] == [
        DealRole.CLIENT,
        DealRole.PERFORMER,
        None,
        None,
    ]
