"""Решения клиента по откликам (DEVELOPMENT_PLAN 6.1a; ARCHITECTURE §7.9): выбрать исполнителем,
«в избранные», отклонить; заявка «в работе», после отмены сделки — снова открыта, после
завершения — завершена."""

from datetime import timedelta

import pytest

from app.modules.jobs.domain.job import CloseReason, Job, JobStatus
from app.modules.jobs.domain.response import (
    Offer,
    Response,
    ResponseId,
    ResponsePriceType,
    ResponseStatus,
)
from app.modules.jobs.errors import JobNotOpenError, ResponseNotActiveError, ResponseNotFoundError
from app.modules.jobs.tests.builders import CLIENT, NOW, published
from app.platform.contracts.events.jobs import JobPublished, ResponseDeclined
from app.platform.kernel.ids import UserId, new_id

pytestmark = pytest.mark.unit

LATER = NOW + timedelta(minutes=30)


def respond(job: Job, *, visible: bool = True) -> Response:
    response = job.respond(
        response_id=ResponseId(new_id()),
        performer_id=UserId(new_id()),
        offer=Offer(message="Могу сегодня", price_type=ResponsePriceType.FIXED, price_amount=1),
        now=NOW,
    )
    if visible:
        assert job.clear_response(response.id, revision=None, now=NOW)
    return response


def assigned() -> tuple[Job, Response, Response]:
    job = published()
    chosen, other = respond(job), respond(job)
    job.accept_response(chosen.id, client_id=CLIENT, now=LATER)
    job.pull_events()
    job.pull_history()
    return job, chosen, other


def test_accept_assigns_the_job_and_frees_the_others() -> None:
    job = published()
    chosen, other, hidden = respond(job), respond(job), respond(job, visible=False)
    job.pull_history()

    response = job.accept_response(chosen.id, client_id=CLIENT, now=LATER)

    assert response is chosen
    assert (chosen.status, chosen.viewed_at, chosen.decided_at) == (
        ResponseStatus.ACCEPTED,
        LATER,
        LATER,
    )
    assert (other.status, hidden.status) == (
        ResponseStatus.NOT_SELECTED,
        ResponseStatus.NOT_SELECTED,
    )
    assert (job.status, job.selected_response_id, job.responses_count) == (
        JobStatus.ASSIGNED,
        chosen.id,
        0,
    )
    [(change, _)] = job.pull_history()
    assert (change.from_, change.to, change.actor_id) == (
        JobStatus.PUBLISHED,
        JobStatus.ASSIGNED,
        CLIENT,
    )


def test_accept_only_a_visible_active_response_of_own_open_job() -> None:
    job = published()
    hidden, withdrawn = respond(job, visible=False), respond(job)
    job.withdraw_response(withdrawn.id, performer_id=withdrawn.performer_id, now=LATER)
    visible = respond(job)

    with pytest.raises(ResponseNotFoundError):  # ещё на проверке — клиент его не видит
        job.accept_response(hidden.id, client_id=CLIENT, now=LATER)
    with pytest.raises(ResponseNotFoundError):  # чужая заявка
        job.accept_response(visible.id, client_id=UserId(new_id()), now=LATER)
    with pytest.raises(ResponseNotActiveError):
        job.accept_response(withdrawn.id, client_id=CLIENT, now=LATER)
    job.close(CloseReason.NOT_NEEDED, now=LATER)
    with pytest.raises(JobNotOpenError):
        job.accept_response(visible.id, client_id=CLIENT, now=LATER)


def test_shortlist_marks_a_favourite_once() -> None:
    job = published()
    response = respond(job)

    job.shortlist_response(response.id, client_id=CLIENT, now=LATER)
    job.shortlist_response(response.id, client_id=CLIENT, now=LATER + timedelta(minutes=1))

    assert (response.status, response.viewed_at) == (ResponseStatus.SHORTLISTED, LATER)
    assert job.responses_count == 1  # «в избранных» место занимает


def test_decline_frees_the_place() -> None:
    job = published()
    response = respond(job)
    job.pull_events()

    job.decline_response(response.id, client_id=CLIENT, now=LATER)

    assert (response.status, job.responses_count) == (ResponseStatus.DECLINED, 0)
    [event] = job.pull_events()
    assert isinstance(event, ResponseDeclined)
    assert event.performer_id == response.performer_id
    with pytest.raises(ResponseNotActiveError):
        job.decline_response(response.id, client_id=CLIENT, now=LATER)


@pytest.mark.parametrize(
    ("by_performer", "status"),
    [(True, ResponseStatus.WITHDRAWN), (False, ResponseStatus.DECLINED)],
)
def test_cancelled_deal_reopens_the_job(by_performer: bool, status: ResponseStatus) -> None:
    job, chosen, other = assigned()
    job.expires_at = LATER  # срок вышел, пока шла сделка

    reopened = job.reopen_after_deal(chosen.id, by_performer=by_performer, now=LATER)

    assert reopened
    assert (job.status, job.selected_response_id, job.responses_count) == (
        JobStatus.PUBLISHED,
        None,
        1,
    )
    assert (chosen.status, other.status, other.decided_at) == (status, ResponseStatus.VIEWED, None)
    assert job.expires_at is not None
    assert job.expires_at > LATER  # новый срок
    [event] = job.pull_events()
    assert isinstance(event, JobPublished)
    assert event.republished
    assert not job.reopen_after_deal(chosen.id, by_performer=by_performer, now=LATER)


def test_completed_deal_completes_the_job() -> None:
    job, chosen, _ = assigned()

    assert not job.complete_after_deal(ResponseId(new_id()), now=LATER)  # чужая сделка
    assert job.complete_after_deal(chosen.id, now=LATER)

    assert (job.status, job.closed_at, job.close_reason) == (
        JobStatus.COMPLETED,
        LATER,
        CloseReason.HIRED_HERE,
    )
    assert not job.complete_after_deal(chosen.id, now=LATER)  # повтор задачи


def test_assigned_job_is_not_closed_or_deleted_by_the_client() -> None:
    job, _, _ = assigned()

    with pytest.raises(JobNotOpenError):
        job.close(CloseReason.NOT_NEEDED, now=LATER)
    with pytest.raises(JobNotOpenError):
        job.delete(now=LATER)
    job.delete(now=LATER, by_system=True)  # аккаунт удалён — закрывается и она

    assert job.status is JobStatus.CLOSED
