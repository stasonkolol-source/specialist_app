"""Отзыв (DEVELOPMENT_PLAN 7.2; ARCHITECTURE §7.9): только клиент, только по завершённой сделке и
не позже 14 дней; проверка публикует или снимает; один ответ исполнителя со своей проверкой;
удаление аккаунта автора стирает отзыв."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.reviews.domain.review import (
    REVIEW_WINDOW,
    Criterion,
    DealFacts,
    RemovalReason,
    ReplyStatus,
    Review,
    ReviewId,
    ReviewStatus,
)
from app.modules.reviews.errors import (
    InvalidReviewError,
    NotReviewSubjectError,
    ReplyExistsError,
    ReviewNotAllowedError,
    ReviewNotFoundError,
)
from app.platform.contracts.events.reviews import ReviewPublished, ReviewRemoved
from app.platform.kernel.ids import CategoryId, DealId, UserId, new_id

pytestmark = pytest.mark.unit

COMPLETED_AT = datetime(2026, 10, 1, 18, 0, tzinfo=UTC)
NOW = COMPLETED_AT + timedelta(days=1)
CLIENT = UserId(new_id())
PERFORMER = UserId(new_id())
PROFILE = new_id()


def deal(**fields: Any) -> DealFacts:
    values: dict[str, Any] = {
        "id": DealId(new_id()),
        "client_id": CLIENT,
        "performer_id": PERFORMER,
        "profile_id": PROFILE,
        "category_id": CategoryId(7),
        "status": "completed",
        "completed_at": COMPLETED_AT,
    }
    return DealFacts(**(values | fields))


def review(*, author: UserId = CLIENT, now: datetime = NOW, **fields: Any) -> Review:
    values: dict[str, Any] = {"rating": 5, "criteria": {}, "body": None} | fields
    facts = values.pop("deal", None) or deal()
    return Review.for_deal(
        review_id=ReviewId(new_id()), deal=facts, author_id=author, now=now, **values
    )


def reply_status(review: Review) -> ReplyStatus | None:
    return review.reply.status if review.reply is not None else None


def published(**fields: Any) -> Review:
    created = review(**fields)
    created.publish(now=NOW)
    created.pull_events()
    return created


def test_client_leaves_a_review_that_waits_for_the_check() -> None:
    created = review(rating=4, criteria={"quality": 5, "price": 3}, body="  Всё хорошо  ")

    assert created.status is ReviewStatus.UNDER_REVIEW
    assert created.awaits_check
    assert not created.visible
    assert created.subject_user_id == PERFORMER
    assert created.subject_profile_id == PROFILE
    assert created.category_id == CategoryId(7)
    assert created.criteria == {Criterion.QUALITY: 5, Criterion.PRICE: 3}
    assert created.body == "Всё хорошо"
    assert created.pull_events() == []


@pytest.mark.parametrize(
    ("facts", "author", "now", "reason"),
    [
        (deal(status="agreed", completed_at=None), CLIENT, NOW, "not_completed"),
        (deal(), PERFORMER, NOW, "not_client"),
        (deal(), CLIENT, COMPLETED_AT + REVIEW_WINDOW + timedelta(seconds=1), "window_closed"),
    ],
)
def test_review_only_by_the_client_of_a_recently_completed_deal(
    facts: DealFacts, author: UserId, now: datetime, reason: str
) -> None:
    with pytest.raises(ReviewNotAllowedError) as raised:
        review(deal=facts, author=author, now=now)
    assert raised.value.params["reason"] == reason


def test_last_moment_of_the_window_still_counts() -> None:
    assert review(now=COMPLETED_AT + REVIEW_WINDOW).awaits_check


@pytest.mark.parametrize(
    ("fields", "field", "reason"),
    [
        ({"rating": 0}, "rating", "range"),
        ({"rating": 6}, "rating", "range"),
        ({"rating": True}, "rating", "range"),
        ({"criteria": {"speed": 5}}, "criteria", "unknown"),
        ({"criteria": {"quality": 9}}, "criteria", "range"),
        ({"body": "x" * 2001}, "body", "length"),
    ],
)
def test_invalid_review_is_refused(fields: dict[str, Any], field: str, reason: str) -> None:
    with pytest.raises(InvalidReviewError) as raised:
        review(**fields)
    assert raised.value.params == {"field": field, "reason": reason}


def test_blank_text_means_rating_only() -> None:
    assert review(body="   ").body is None


def test_check_publishes_once_and_tells_the_rating() -> None:
    created = review(rating=4, body="Ок")

    assert created.publish(now=NOW) is True
    assert created.publish(now=NOW) is False

    assert created.visible
    assert created.published_at == NOW
    [event] = created.pull_events()
    assert isinstance(event, ReviewPublished)
    assert (event.subject_profile_id, event.rating, event.has_text) == (PROFILE, 4, True)


def test_removing_a_published_review_changes_the_rating_and_an_unchecked_one_does_not() -> None:
    unchecked = review()
    assert unchecked.remove(reason=RemovalReason.MODERATION, now=NOW) is True
    assert unchecked.status is ReviewStatus.REMOVED
    assert unchecked.pull_events() == []
    assert unchecked.publish(now=NOW) is False  # снятый не публикуется

    shown = published()
    assert shown.remove(reason=RemovalReason.MODERATION, now=NOW) is True
    [event] = shown.pull_events()
    assert isinstance(event, ReviewRemoved)
    assert event.reason == "moderation"


def test_subject_replies_once_and_the_reply_waits_for_its_own_check() -> None:
    shown = published()

    shown.add_reply(author_id=PERFORMER, body=" Спасибо! ", now=NOW)

    assert shown.reply is not None
    assert shown.reply.body == "Спасибо!"
    assert reply_status(shown) is ReplyStatus.UNDER_REVIEW
    with pytest.raises(ReplyExistsError):
        shown.add_reply(author_id=PERFORMER, body="Ещё", now=NOW)
    assert shown.publish_reply(now=NOW) is True
    assert reply_status(shown) is ReplyStatus.PUBLISHED
    assert shown.remove_reply(now=NOW) is True
    assert reply_status(shown) is ReplyStatus.REMOVED
    assert shown.visible  # отзыв остаётся
    with pytest.raises(ReplyExistsError):  # скрытый ответ — второго не будет
        shown.add_reply(author_id=PERFORMER, body="Ещё", now=NOW)


def test_only_the_subject_replies_and_only_to_a_published_review() -> None:
    with pytest.raises(ReviewNotFoundError):
        review().add_reply(author_id=PERFORMER, body="Спасибо", now=NOW)
    shown = published()
    with pytest.raises(NotReviewSubjectError):
        shown.add_reply(author_id=CLIENT, body="Спасибо", now=NOW)
    with pytest.raises(InvalidReviewError):
        shown.add_reply(author_id=PERFORMER, body="  ", now=NOW)


def test_erasing_the_author_removes_the_review_and_its_text() -> None:
    shown = published(body="Текст", criteria={"quality": 5})

    shown.erase(now=NOW)
    shown.erase(now=NOW)  # повтор — ничего

    assert shown.status is ReviewStatus.REMOVED
    assert (shown.body, shown.criteria, shown.deleted_at) == (None, {}, NOW)
    [event] = shown.pull_events()
    assert isinstance(event, ReviewRemoved)
    assert event.reason == "author_deleted"
