"""Адаптер цели «работа портфолио» (DEVELOPMENT_PLAN 6.7): подпись проверяется, когда фото
прошло проверку; портфолио нового профиля — всегда человек, в кейсе профиля (B5); решения —
через фасад specialists."""

from collections.abc import Mapping
from typing import Any, Self, cast
from uuid import UUID

import pytest

from app.modules.media.api import MediaModeration, ModerationVerdict
from app.modules.moderation.infrastructure.targets.portfolio import PortfolioTarget
from app.modules.specialists.api import SpecialistsApi, WorkForReview
from app.platform.ai.port import ContentKind
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import MediaId, UserId, new_id

OWNER = UserId(new_id())
MEDIA = MediaId(new_id())
PROFILE = new_id()


class Transactions:
    def __init__(self) -> None:
        self.opened = 0

    async def __aenter__(self) -> Self:
        self.opened += 1
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class Media:
    def __init__(self, verdict: ModerationVerdict | None) -> None:
        self.verdict_ = verdict

    async def verdict(self, media_id: MediaId) -> ModerationVerdict | None:
        assert media_id == MEDIA
        return self.verdict_

    async def moderate(
        self,
        media_id: MediaId,
        verdict: ModerationVerdict,
        *,
        labels: Mapping[str, float] | None = None,
        auto: bool = False,
    ) -> bool:
        raise AssertionError("адаптер работы файл не трогает")


class Specialists:
    def __init__(self, work: WorkForReview | None) -> None:
        self.work = work
        self.calls: list[tuple[str, UUID]] = []
        self.versions: list[int | None] = []

    async def work_for_review(self, work_id: UUID) -> WorkForReview | None:
        return self.work

    async def approve_work(
        self, work_id: UUID, *, version: int | None = None, auto: bool = False
    ) -> None:
        self.calls.append(("auto_approve" if auto else "approve", work_id))
        self.versions.append(version)

    async def reject_work(self, work_id: UUID) -> None:
        self.calls.append(("reject", work_id))


def review(
    *,
    pending: bool = True,
    new_profile: bool = False,
    caption: str | None = "Люстра",
    profile_status: str = "published",
) -> Any:
    return WorkForReview(
        user_id=OWNER,
        caption=caption,
        media_id=MEDIA,
        revision=3,
        pending=pending,
        new_profile=new_profile,
        risk_level=1,
        profile_id=PROFILE,
        profile_status=profile_status,
    )


def target(
    work: WorkForReview | None, verdict: ModerationVerdict | None
) -> tuple[PortfolioTarget, Specialists, Transactions]:
    specialists, uow = Specialists(work), Transactions()
    adapter = PortfolioTarget(
        cast(UnitOfWork, uow),
        cast(SpecialistsApi, specialists),
        cast(MediaModeration, Media(verdict)),
    )
    return adapter, specialists, uow


async def test_caption_is_checked_once_the_photo_is_approved() -> None:
    adapter, _, uow = target(review(), ModerationVerdict.APPROVED)

    content = await adapter.content(new_id())

    assert content is not None
    assert (content.author_id, content.kind, content.text) == (OWNER, ContentKind.PROFILE, "Люстра")
    assert (content.media_ids, content.always_review, content.risk_level) == ((MEDIA,), False, 1)
    assert content.version == 3  # редакция подписи: кейс помнит её (ADV-11)
    assert uow.opened == 1  # итог фото — под блокировкой строки, в своей транзакции


async def test_approval_publishes_only_the_reviewed_caption() -> None:
    adapter, specialists, _ = target(review(), ModerationVerdict.APPROVED)

    await adapter.publish(new_id(), version=3)

    assert specialists.versions == [3]  # подпись правили после карточки — фасад не опубликует


@pytest.mark.parametrize(
    "verdict", [None, ModerationVerdict.FLAGGED, ModerationVerdict.REJECTED], ids=str
)
async def test_waits_while_the_photo_is_unchecked_flagged_or_hidden(
    verdict: ModerationVerdict | None,
) -> None:
    adapter, _, _ = target(review(), verdict)

    assert await adapter.content(new_id()) is None


async def test_portfolio_of_a_new_profile_goes_to_the_profile_case() -> None:
    """B5, Q34: работа профиля на первой проверке — повод в кейс профиля, а не свой кейс; ждать
    фото не нужно: модератор профиля увидит его в том же кейсе."""
    work = review(new_profile=True, caption=None, profile_status="pending_review")
    adapter, _, uow = target(work, None)

    content = await adapter.content(new_id())

    assert content is not None
    assert (content.text, content.always_review, content.profile_case) == ("", True, PROFILE)
    assert content.media_ids == (MEDIA,)
    assert uow.opened == 0


async def test_portfolio_of_a_draft_profile_waits_for_the_profile() -> None:
    work = review(new_profile=True, profile_status="draft")
    adapter, _, _ = target(work, ModerationVerdict.APPROVED)

    assert await adapter.content(new_id()) is None  # проверят вместе с профилем при отправке


async def test_portfolio_of_a_never_published_visible_profile_still_goes_to_a_human() -> None:
    adapter, _, _ = target(review(new_profile=True, caption=None), ModerationVerdict.APPROVED)

    content = await adapter.content(new_id())

    assert content is not None
    assert (content.text, content.always_review, content.profile_case) == ("", True, None)


async def test_caption_edit_of_published_work_is_post_moderated() -> None:
    adapter, _, uow = target(review(pending=False, new_profile=True), None)

    content = await adapter.content(new_id())

    assert content is not None
    assert content.always_review is False  # видна, проверяется только правка
    assert uow.opened == 0  # фото уже проверено до публикации


async def test_missing_work_has_nothing_to_check() -> None:
    adapter, _, _ = target(None, ModerationVerdict.APPROVED)

    assert await adapter.content(new_id()) is None


async def test_decisions_publish_or_hide_the_work() -> None:
    adapter, specialists, _ = target(review(), ModerationVerdict.APPROVED)
    work_id = new_id()

    await adapter.publish(work_id)
    await adapter.hide(work_id, reason_code="contact_leak")
    await adapter.publish(work_id, auto=True)  # итог автопроверки: скрытую — не возвращает

    assert specialists.calls == [
        ("approve", work_id),
        ("reject", work_id),
        ("auto_approve", work_id),
    ]
