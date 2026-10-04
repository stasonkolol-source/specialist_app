"""Работа портфолио (DEVELOPMENT_PLAN 2.11, 6.7): новая ждёт проверки, решение публикует или
скрывает; запрос проверки — новой и правки подписи, но не скрытой."""

from datetime import UTC, datetime
from typing import Self

from app.modules.specialists.application.profiles import PORTFOLIO_WORK, request_work_review
from app.modules.specialists.domain.portfolio import PortfolioItem, WorkKind, WorkStatus
from app.platform.contracts.events.moderation import ModerationRequested
from app.platform.kernel.events import DomainEvent
from app.platform.kernel.ids import MediaId, UserId, new_id

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)
OWNER = UserId(new_id())


def work() -> PortfolioItem:
    return PortfolioItem.add(
        profile_id=new_id(),
        media_id=MediaId(new_id()),
        kind=WorkKind.IMAGE,
        caption="  Люстра   в гостиной ",
        position=0,
        now=NOW,
    )


class Events:
    """UnitOfWork для `request_work_review`: только события."""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def add_event(self, event: DomainEvent) -> None:
        self.events.append(event)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def track(self, aggregate: object) -> None: ...

    def require_active(self) -> None: ...


def test_new_work_waits_for_review() -> None:
    item = work()

    assert (item.status, item.pending, item.caption) == (
        WorkStatus.PENDING,
        True,
        "Люстра в гостиной",
    )


def test_approval_publishes_once() -> None:
    item = work()

    assert item.approve()
    assert (item.status, item.pending) == (WorkStatus.PUBLISHED, False)
    assert not item.approve()  # повтор решения — ничего


def state(item: PortfolioItem) -> WorkStatus:
    return item.status


def test_rejection_hides_and_moderator_can_return_the_work() -> None:
    item = work()

    assert item.reject()
    assert state(item) is WorkStatus.REJECTED
    assert not item.reject()
    # P0 автопроверки скрыл работу, модератор не нашёл нарушения — работа видна
    assert item.approve()
    assert state(item) is WorkStatus.PUBLISHED


def test_late_auto_check_does_not_return_a_work_the_moderator_hid() -> None:
    """Автопроверка подписи шла, модератор тем временем скрыл работу: её чистый итог опоздал."""
    item = work()
    item.reject()

    assert not item.approve(auto=True)
    assert state(item) is WorkStatus.REJECTED
    assert item.approve()  # решение модератора — возвращает


def test_auto_check_publishes_a_waiting_work() -> None:
    item = work()

    assert item.approve(auto=True)
    assert state(item) is WorkStatus.PUBLISHED


def test_new_work_and_caption_edit_request_review() -> None:
    uow = Events()
    item = work()

    request_work_review(uow, item, OWNER, now=NOW)
    item.approve()
    request_work_review(uow, item, OWNER, now=NOW)

    assert all(isinstance(event, ModerationRequested) for event in uow.events)
    requested = [
        (e.entity_type, e.entity_id, e.author_id, e.edit)
        for e in uow.events
        if isinstance(e, ModerationRequested)
    ]
    assert requested == [
        (PORTFOLIO_WORK, item.id, OWNER, False),  # новая — до публикации
        (PORTFOLIO_WORK, item.id, OWNER, True),  # правка опубликованной — пост-модерация
    ]


def test_hidden_work_is_not_reviewed_again() -> None:
    uow = Events()
    item = work()
    item.reject()

    request_work_review(uow, item, OWNER, now=NOW)

    assert uow.events == []
