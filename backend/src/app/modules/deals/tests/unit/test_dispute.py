"""Спор по сделке (DEVELOPMENT_PLAN 6.1c; ARCHITECTURE §7.9, §14.4): открыть по идущей сделке,
ответ второй стороны, «нет ответа» через 48 ч, отзыв открывшим и решение модератора."""

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.deals.domain.deal import (
    ActorKind,
    Deal,
    DealCancelReason,
    DealPriceType,
    DealStatus,
    DealTerms,
)
from app.modules.deals.domain.dispute import (
    MAX_PHOTOS,
    MAX_TEXT,
    RESPONSE_WINDOW,
    Dispute,
    DisputeId,
    DisputeKind,
    DisputeOutcome,
    DisputeStatus,
)
from app.modules.deals.errors import (
    DealNotActiveError,
    DealNotFoundError,
    DisputeStateError,
    InvalidDisputeError,
)
from app.platform.contracts.events.deals import (
    DealCancelled,
    DealCompleted,
    DealDisputed,
    DisputeAnswered,
    DisputeResolved,
    DisputeUnanswered,
    DisputeWithdrawn,
)
from app.platform.kernel.ids import CategoryId, DealId, MediaId, UserId, new_id

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 3, 19, 40, tzinfo=UTC)
CLIENT = UserId(new_id())
PERFORMER = UserId(new_id())
STRANGER = UserId(new_id())
MODERATOR = UserId(new_id())
PHOTO = MediaId(new_id())


def agreed() -> Deal:
    deal = Deal.agree_from_response(
        deal_id=DealId(new_id()),
        client_id=CLIENT,
        performer_id=PERFORMER,
        profile_id=None,
        job_id=new_id(),
        response_id=new_id(),
        terms=DealTerms(
            title="Повесить люстру",
            category_id=CategoryId(5),
            price_type=DealPriceType.FIXED,
            agreed_price=350_000,
        ),
        now=NOW - timedelta(hours=4),
    )
    deal.pull_events()
    deal.pull_history()
    return deal


def opened(deal: Deal, by: UserId = CLIENT) -> Dispute:
    return Dispute.open(
        dispute_id=DisputeId(new_id()),
        deal=deal,
        actor_id=by,
        kind=DisputeKind.NO_SHOW,
        description="  Договорились на 19:00. В 19:40 мастера нет, на сообщения не отвечает. ",
        media_ids=(PHOTO, PHOTO),
        now=NOW,
    )


def status_of(dispute: Dispute) -> DisputeStatus:
    """Статус после действия: mypy не сужает его по прошлому assert."""
    return dispute.status


def test_open_disputes_the_deal_and_gives_48_hours() -> None:
    deal = agreed()

    dispute = opened(deal)

    assert deal.status is DealStatus.DISPUTED
    assert (dispute.status, dispute.respondent_id) == (DisputeStatus.OPEN, PERFORMER)
    assert dispute.respond_by == NOW + RESPONSE_WINDOW
    assert dispute.description.startswith("Договорились")  # без пробелов по краям
    assert dispute.media_ids == (PHOTO,)  # повтор одного файла — один
    [change] = deal.pull_history()
    assert (change.from_, change.to, change.actor_id, change.actor_kind) == (
        DealStatus.AGREED,
        DealStatus.DISPUTED,
        CLIENT,
        ActorKind.USER,
    )
    [event] = dispute.pull_events()
    assert isinstance(event, DealDisputed)
    assert (event.opened_by, event.respondent_id, event.kind) == (CLIENT, PERFORMER, "no_show")
    assert event.media_ids == (PHOTO,)


def test_performer_can_open_a_dispute_too() -> None:
    dispute = opened(agreed(), by=PERFORMER)

    assert dispute.respondent_id == CLIENT


def test_only_a_party_of_an_agreed_deal_opens_a_dispute() -> None:
    with pytest.raises(DealNotFoundError):
        opened(agreed(), by=STRANGER)
    deal = agreed()
    deal.complete(actor_id=CLIENT, now=NOW)
    deal.complete(actor_id=PERFORMER, now=NOW)
    with pytest.raises(DealNotActiveError):
        opened(deal)
    disputed = agreed()
    opened(disputed)
    with pytest.raises(DealNotActiveError):  # второй спор по той же сделке
        opened(disputed, by=PERFORMER)


@pytest.mark.parametrize(
    ("description", "photos", "field", "reason"),
    [
        ("   ", (), "description", "empty"),
        ("а" * (MAX_TEXT + 1), (), "description", "too_long"),
        (
            "Не пришёл",
            tuple(MediaId(new_id()) for _ in range(MAX_PHOTOS + 1)),
            "media_ids",
            "too_many",
        ),
    ],
)
def test_invalid_dispute_leaves_the_deal_agreed(
    description: str, photos: tuple[MediaId, ...], field: str, reason: str
) -> None:
    deal = agreed()

    with pytest.raises(InvalidDisputeError) as caught:
        Dispute.open(
            dispute_id=DisputeId(new_id()),
            deal=deal,
            actor_id=CLIENT,
            kind=DisputeKind.OTHER,
            description=description,
            media_ids=photos,
            now=NOW,
        )

    assert caught.value.params == {"field": field, "reason": reason}
    assert deal.status is DealStatus.AGREED


def test_disputed_deal_is_frozen() -> None:
    deal = agreed()
    opened(deal)

    with pytest.raises(DealNotActiveError):
        deal.complete(actor_id=CLIENT, now=NOW)
    with pytest.raises(DealNotActiveError):
        deal.cancel(actor_id=CLIENT, reason=DealCancelReason.OTHER, now=NOW)
    assert not deal.cancel_by_system(reason=DealCancelReason.ACCOUNT_DELETED, now=NOW)
    assert not deal.prompt_completion(now=NOW + timedelta(days=2))


def test_respondent_answers_once() -> None:
    dispute = opened(agreed())
    dispute.pull_events()

    dispute.respond(actor_id=PERFORMER, text=" Пробки, был в 20:10 ", media_ids=(), now=NOW)

    assert (dispute.status, dispute.response, dispute.responded_at) == (
        DisputeStatus.ANSWERED,
        "Пробки, был в 20:10",
        NOW,
    )
    [event] = dispute.pull_events()
    assert isinstance(event, DisputeAnswered)
    with pytest.raises(DisputeStateError) as again:
        dispute.respond(actor_id=PERFORMER, text="Ещё", media_ids=(), now=NOW)
    assert again.value.params["reason"] == "not_awaiting"


def test_opener_does_not_answer_own_dispute() -> None:
    dispute = opened(agreed())

    with pytest.raises(DisputeStateError) as caught:
        dispute.respond(actor_id=CLIENT, text="Сам себе", media_ids=(), now=NOW)

    assert caught.value.params == {"dispute_status": "open", "reason": "not_respondent"}


def test_no_answer_in_48_hours_marks_once_and_late_answer_is_accepted() -> None:
    dispute = opened(agreed())
    dispute.pull_events()

    assert not dispute.mark_unanswered(now=NOW + RESPONSE_WINDOW - timedelta(minutes=1))
    assert dispute.mark_unanswered(now=NOW + RESPONSE_WINDOW)
    assert not dispute.mark_unanswered(now=NOW + RESPONSE_WINDOW + timedelta(hours=1))

    assert status_of(dispute) is DisputeStatus.NO_RESPONSE
    [event] = dispute.pull_events()
    assert isinstance(event, DisputeUnanswered)
    dispute.respond(actor_id=PERFORMER, text="Не видел уведомление", media_ids=(), now=NOW)
    assert status_of(dispute) is DisputeStatus.ANSWERED


def test_answered_dispute_is_not_marked_unanswered() -> None:
    dispute = opened(agreed())
    dispute.respond(actor_id=PERFORMER, text="Был на месте", media_ids=(), now=NOW)

    assert not dispute.mark_unanswered(now=NOW + RESPONSE_WINDOW * 2)


def test_opener_withdraws_and_the_deal_goes_on() -> None:
    deal = agreed()
    dispute = opened(deal)
    deal.pull_history()
    dispute.pull_events()

    with pytest.raises(DisputeStateError):
        dispute.withdraw(deal=deal, actor_id=PERFORMER, now=NOW)
    dispute.withdraw(deal=deal, actor_id=CLIENT, now=NOW)

    assert (dispute.status, deal.status) == (DisputeStatus.WITHDRAWN, DealStatus.AGREED)
    [change] = deal.pull_history()
    assert (change.from_, change.to, change.reason) == (
        DealStatus.DISPUTED,
        DealStatus.AGREED,
        "dispute_withdrawn",
    )
    [event] = dispute.pull_events()
    assert isinstance(event, DisputeWithdrawn)
    with pytest.raises(DisputeStateError):
        dispute.withdraw(deal=deal, actor_id=CLIENT, now=NOW)
    deal.complete(actor_id=CLIENT, now=NOW)  # сделка снова идёт


def test_moderator_completes_the_deal() -> None:
    deal = agreed()
    dispute = opened(deal)
    deal.pull_history()
    dispute.pull_events()

    dispute.resolve(
        deal=deal,
        outcome=DisputeOutcome.COMPLETED,
        reason_code="work_done",
        moderator_id=MODERATOR,
        now=NOW,
    )

    assert (deal.status, deal.completed_at) == (DealStatus.COMPLETED, NOW)
    assert (dispute.status, dispute.outcome, dispute.resolved_by) == (
        DisputeStatus.RESOLVED,
        DisputeOutcome.COMPLETED,
        MODERATOR,
    )
    [change] = deal.pull_history()
    assert (change.to, change.actor_id, change.actor_kind) == (
        DealStatus.COMPLETED,
        MODERATOR,
        ActorKind.MODERATOR,
    )
    [completed] = deal.pull_events()
    assert isinstance(completed, DealCompleted)
    assert not completed.auto
    [resolved] = dispute.pull_events()
    assert isinstance(resolved, DisputeResolved)
    assert (resolved.outcome, resolved.reason_code) == ("completed", "work_done")


def test_moderator_cancels_the_deal() -> None:
    deal = agreed()
    dispute = opened(deal)
    deal.pull_history()

    dispute.resolve(
        deal=deal,
        outcome=DisputeOutcome.CANCELLED,
        reason_code="no_show",
        moderator_id=MODERATOR,
        now=NOW,
    )

    assert (deal.status, deal.cancel_reason, deal.cancelled_by) == (
        DealStatus.CANCELLED,
        DealCancelReason.DISPUTE,
        None,  # не «отменил я» и не «вторая сторона»
    )
    [change] = deal.pull_history()
    assert (change.actor_id, change.actor_kind, change.reason) == (
        MODERATOR,
        ActorKind.MODERATOR,
        "dispute",
    )
    [cancelled] = deal.pull_events()
    assert isinstance(cancelled, DealCancelled)
    assert (cancelled.cancelled_by, cancelled.reason) == ("moderator", "dispute")


def test_resolved_or_withdrawn_dispute_is_not_resolved_again() -> None:
    deal = agreed()
    dispute = opened(deal)
    dispute.withdraw(deal=deal, actor_id=CLIENT, now=NOW)

    with pytest.raises(DisputeStateError):
        dispute.resolve(
            deal=deal,
            outcome=DisputeOutcome.CANCELLED,
            reason_code="no_show",
            moderator_id=MODERATOR,
            now=NOW,
        )
    assert deal.status is DealStatus.AGREED


def test_reason_code_is_required() -> None:
    deal = agreed()
    dispute = opened(deal)

    with pytest.raises(InvalidDisputeError):
        dispute.resolve(
            deal=deal,
            outcome=DisputeOutcome.COMPLETED,
            reason_code="",
            moderator_id=MODERATOR,
            now=NOW,
        )
    assert deal.status is DealStatus.DISPUTED
