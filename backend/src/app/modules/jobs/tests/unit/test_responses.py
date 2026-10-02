"""Отклик (DEVELOPMENT_PLAN 5.4; ARCHITECTURE §7.9): подагрегат заявки — места, один отклик от
исполнителя, правка и отзыв, проверка модерацией, закрытие заявки, предложение."""

from datetime import timedelta

import pytest

from app.modules.jobs.domain.job import CloseReason, Job
from app.modules.jobs.domain.response import (
    MAX_AVAILABILITY,
    MAX_MESSAGE,
    Offer,
    PriceType,
    Response,
    ResponseId,
    ResponseStatus,
    Review,
)
from app.modules.jobs.errors import (
    AlreadyRespondedError,
    InvalidResponseError,
    JobFullError,
    JobNotOpenError,
    OwnJobResponseError,
    ResponseNotActiveError,
    ResponseNotFoundError,
)
from app.modules.jobs.tests.builders import CLIENT, NOW, published, submitted
from app.platform.contracts.events.jobs import (
    ResponseSubmitted,
    ResponseUpdated,
    ResponseWithdrawn,
)
from app.platform.kernel.ids import UserId, new_id

pytestmark = pytest.mark.unit

LATER = NOW + timedelta(minutes=5)


def offer(message: str = "Могу сегодня в 19:00, свой инструмент.") -> Offer:
    return Offer(message=message, price_type=PriceType.FIXED, price_amount=350_000)


def performer() -> UserId:
    return UserId(new_id())


def respond(job: Job, who: UserId | None = None) -> Response:
    return job.respond(
        response_id=ResponseId(new_id()), performer_id=who or performer(), offer=offer(), now=LATER
    )


def test_response_takes_a_place_and_waits_for_the_check() -> None:
    job = published()

    first = respond(job)
    respond(job)

    assert (first.status, first.review, first.revision) == (
        ResponseStatus.SUBMITTED,
        Review.PENDING,
        1,
    )
    assert job.responses_count == 2
    events = job.pull_events()
    assert [type(e) for e in events] == [ResponseSubmitted, ResponseSubmitted]
    assert [e.is_first for e in events if isinstance(e, ResponseSubmitted)] == [True, False]
    assert all(
        e.published_at == NOW and e.client_id == CLIENT
        for e in events
        if isinstance(e, ResponseSubmitted)
    )


def test_responding_refuses_own_repeated_full_and_not_open() -> None:
    job = published()
    job.max_responses = 2
    someone = performer()
    respond(job, someone)

    with pytest.raises(OwnJobResponseError):
        respond(job, CLIENT)
    with pytest.raises(AlreadyRespondedError):
        respond(job, someone)
    respond(job)
    with pytest.raises(JobFullError) as full:
        respond(job)
    assert full.value.params["limit"] == 2
    with pytest.raises(JobNotOpenError):
        respond(submitted())


def test_withdrawn_response_frees_the_place_and_is_not_repeated() -> None:
    job = published()
    someone = performer()
    response = respond(job, someone)
    job.pull_events()

    job.withdraw_response(response.id, performer_id=someone, now=LATER)

    assert (response.status, job.responses_count) == (ResponseStatus.WITHDRAWN, 0)
    assert [type(e) for e in job.pull_events()] == [ResponseWithdrawn]
    with pytest.raises(ResponseNotActiveError):
        job.withdraw_response(response.id, performer_id=someone, now=LATER)
    with pytest.raises(AlreadyRespondedError):
        respond(job, someone)
    with pytest.raises(ResponseNotFoundError):
        job.withdraw_response(response.id, performer_id=performer(), now=LATER)


def test_revised_response_is_checked_again() -> None:
    job = published()
    someone = performer()
    response = respond(job, someone)
    assert job.clear_response(response.id, revision=1, now=LATER)
    job.pull_events()

    job.revise_response(
        response.id, performer_id=someone, offer=offer("Могу завтра утром."), now=LATER
    )

    assert (response.review, response.revision) == (Review.PENDING, 2)
    assert response.offer.message == "Могу завтра утром."
    assert [type(e) for e in job.pull_events()] == [ResponseUpdated]
    # проверка старой редакции не показывает новую
    assert not job.clear_response(response.id, revision=1, now=LATER)
    assert job.clear_response(response.id, revision=2, now=LATER)
    assert response.visible_to_client


def test_blocked_response_is_hidden_and_frees_the_place() -> None:
    job = published()
    response = respond(job)

    assert job.block_response(response.id, now=LATER)

    assert (response.review, response.status) == (Review.BLOCKED, ResponseStatus.WITHDRAWN)
    assert job.responses_count == 0
    assert not job.block_response(response.id, now=LATER)
    assert not job.clear_response(response.id, revision=None, now=LATER)
    assert not job.clear_response(ResponseId(new_id()), revision=None, now=LATER)


def test_closed_job_does_not_select_active_responses() -> None:
    job = published()
    active = respond(job)
    withdrawn_by = performer()
    withdrawn = respond(job, withdrawn_by)
    job.withdraw_response(withdrawn.id, performer_id=withdrawn_by, now=LATER)

    job.close(CloseReason.NOT_NEEDED, now=LATER)

    assert (active.status, active.decided_at) == (ResponseStatus.NOT_SELECTED, LATER)
    assert withdrawn.status is ResponseStatus.WITHDRAWN
    assert job.responses_count == 0


def test_response_change_marks_only_that_response_for_saving() -> None:
    job = published()
    response = respond(job)
    response.mark_saved()
    untouched = respond(job)
    untouched.mark_saved()

    job.withdraw_response(response.id, performer_id=response.performer_id, now=LATER)

    assert (response.changed, untouched.changed) == (True, False)


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"message": "   "}, "message"),
        ({"message": "м" * (MAX_MESSAGE + 1)}, "message"),
        ({"price_type": PriceType.NEGOTIABLE, "price_amount": 100}, "price_amount"),
        ({"price_type": PriceType.FROM, "price_amount": None}, "price_amount"),
        ({"price_amount": 0}, "price_amount"),
        ({"availability_note": "з" * (MAX_AVAILABILITY + 1)}, "availability_note"),
    ],
)
def test_offer_rules(fields: dict[str, object], field: str) -> None:
    values: dict[str, object] = {
        "message": "Могу сегодня",
        "price_type": PriceType.FIXED,
        "price_amount": 100,
    }
    with pytest.raises(InvalidResponseError) as error:
        Offer(**(values | fields))  # type: ignore[arg-type]
    assert error.value.params["field"] == field


def test_offer_trims_text_and_drops_an_empty_note() -> None:
    trimmed = Offer(
        message="  Могу сегодня  ", price_type=PriceType.NEGOTIABLE, availability_note="  "
    )

    assert (trimmed.message, trimmed.availability_note) == ("Могу сегодня", None)
