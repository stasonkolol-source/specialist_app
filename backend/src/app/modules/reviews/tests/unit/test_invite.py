"""«Отзывы до платформы» (DEVELOPMENT_PLAN 7.6а; ADR-0016): не больше пяти занятых мест на профиль,
ссылка живёт 30 дней и принимает один отзыв, статусы для S55; отзыв по приглашению — с отдельной
меткой, о себе его не оставить, и ни публикация, ни снятие не трогают рейтинг."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.reviews.domain.invite import (
    INVITE_TTL,
    MAX_INVITES,
    InviteStatus,
    ReviewInvite,
    new_token,
)
from app.modules.reviews.domain.review import (
    RemovalReason,
    Review,
    ReviewId,
    ReviewKind,
    ReviewStatus,
)
from app.modules.reviews.errors import (
    InvalidReviewError,
    OwnProfileReviewError,
    ReviewInviteNotFoundError,
    ReviewInvitesFullError,
)
from app.platform.kernel.ids import UserId, new_id

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
PROFILE = new_id()
SPECIALIST = UserId(new_id())
CLIENT = UserId(new_id())


def invite(*, taken: int = 0, now: datetime = NOW, name: str | None = None) -> ReviewInvite:
    return ReviewInvite.issue(
        token=new_token(), profile_id=PROFILE, client_name=name, taken=taken, now=now
    )


def pre_platform(**fields: Any) -> Review:
    values: dict[str, Any] = {
        "author_id": CLIENT,
        "rating": 5,
        "work_title": " Проводка в ванной ",
        "body": "Поменял проводку и повесил светильники.",
    } | fields
    return Review.pre_platform(
        review_id=ReviewId(new_id()),
        subject_user_id=SPECIALIST,
        subject_profile_id=PROFILE,
        now=NOW,
        **values,
    )


def test_tokens_are_random_v4_secrets() -> None:
    tokens = {new_token() for _ in range(100)}
    assert len(tokens) == 100
    assert {token.version for token in tokens} == {4}


def test_sixth_slot_is_refused_and_the_name_is_trimmed() -> None:
    fifth = invite(taken=MAX_INVITES - 1, name="  Андрей В. ")
    assert fifth.client_name == "Андрей В."
    assert fifth.expires_at == NOW + INVITE_TTL
    with pytest.raises(ReviewInvitesFullError) as refused:
        invite(taken=MAX_INVITES)
    assert refused.value.params == {"limit": MAX_INVITES}
    with pytest.raises(InvalidReviewError):
        invite(name="А" * 61)


def test_expired_link_frees_its_slot_and_a_used_one_keeps_it() -> None:
    waiting, used = invite(), invite()
    used.use(by=CLIENT, review_id=new_id(), now=NOW + timedelta(days=1))
    later = NOW + INVITE_TTL
    assert waiting.takes_slot(NOW)
    assert not waiting.takes_slot(later)
    assert used.takes_slot(later)


def test_link_takes_one_review_while_it_lives() -> None:
    fresh = invite()
    assert fresh.usable(NOW)
    fresh.use(by=CLIENT, review_id=new_id(), now=NOW)
    with pytest.raises(ReviewInviteNotFoundError):
        fresh.use(by=UserId(new_id()), review_id=new_id(), now=NOW)
    stale = invite()
    with pytest.raises(ReviewInviteNotFoundError):
        stale.use(by=CLIENT, review_id=new_id(), now=NOW + INVITE_TTL)


@pytest.mark.parametrize(
    ("used", "review_status", "at", "expected"),
    [
        (False, None, NOW, InviteStatus.WAITING),
        (False, None, NOW + INVITE_TTL, InviteStatus.EXPIRED),
        (True, "under_review", NOW, InviteStatus.UNDER_REVIEW),
        (True, "published", NOW + INVITE_TTL, InviteStatus.PUBLISHED),
        (True, "removed", NOW, InviteStatus.REMOVED),
    ],
)
def test_status_badges_of_s55(
    used: bool,
    review_status: str | None,
    at: datetime,
    expected: InviteStatus,
) -> None:
    found = invite()
    if used:
        found.use(by=CLIENT, review_id=new_id(), now=NOW)
    assert found.status(review_status, at) is expected


def test_pre_platform_review_is_labelled_and_waits_for_a_moderator() -> None:
    review = pre_platform()
    assert review.kind is ReviewKind.PRE_PLATFORM
    assert (review.deal_id, review.category_id, review.criteria) == (None, None, {})
    assert review.work_title == "Проводка в ванной"
    assert review.status is ReviewStatus.UNDER_REVIEW
    assert not review.rated
    with pytest.raises(OwnProfileReviewError):
        pre_platform(author_id=SPECIALIST)
    with pytest.raises(InvalidReviewError):
        pre_platform(rating=6)
    with pytest.raises(InvalidReviewError):
        pre_platform(work_title="ы" * 121)


def test_pre_platform_review_never_touches_the_rating() -> None:
    """Ни ReviewPublished, ни ReviewRemoved: рейтинг, review rate и уведомления их не видят."""
    review = pre_platform()
    assert review.publish(now=NOW)
    assert review.visible
    assert review.published_at == NOW
    assert review.pull_events() == []
    assert review.remove(reason=RemovalReason.MODERATION, now=NOW)
    assert review.pull_events() == []
    review.erase(now=NOW)
    assert (review.work_title, review.body) == (None, None)
