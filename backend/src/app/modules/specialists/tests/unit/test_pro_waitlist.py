"""Лист ожидания Pro (Q24, DEVELOPMENT_PLAN 2.7b): «Хочу узнать первым» в рассылке.

Отметка ставится один раз: повторное нажатие не меняет время и не публикует событие второй
раз (аналитика `pro_waitlist_joined` считает людей, а не нажатия).
"""

from dataclasses import dataclass, field
from datetime import timedelta

from app.modules.specialists.application.use_cases.join_pro_waitlist import (
    JoinProWaitlist,
    JoinProWaitlistCommand,
    WaitlistOutcome,
)
from app.modules.specialists.domain.profile import Profile
from app.modules.specialists.tests.unit.test_profile import NOW, draft
from app.platform.contracts.events.specialists import ProWaitlistJoined
from app.platform.kernel.ids import UserId, new_id
from app.platform.testing.clock import FakeClock


def test_joining_the_waitlist_is_idempotent() -> None:
    profile = draft()
    profile.pull_events()
    broadcast_id = new_id()

    assert profile.join_pro_waitlist(now=NOW, broadcast_id=broadcast_id)
    assert not profile.join_pro_waitlist(now=NOW + timedelta(hours=1))

    assert profile.pro_waitlist_at == NOW
    [event] = profile.pull_events()
    assert isinstance(event, ProWaitlistJoined)
    assert (event.user_id, event.broadcast_id) == (profile.user_id, broadcast_id)


@dataclass
class _Profiles:
    by_user: dict[UserId, Profile] = field(default_factory=dict)
    saved: int = 0

    async def of_user(self, user_id: UserId) -> Profile | None:
        return self.by_user.get(user_id)

    async def save(self, profile: Profile) -> None:
        self.saved += 1


class _Uow:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> None:
        return None


async def test_use_case_answers_joined_already_and_no_profile() -> None:
    profile = draft()
    profiles = _Profiles(by_user={profile.user_id: profile})
    join = JoinProWaitlist(_Uow(), profiles, FakeClock(NOW))  # type: ignore[arg-type]

    first = await join(JoinProWaitlistCommand(user_id=profile.user_id))
    second = await join(JoinProWaitlistCommand(user_id=profile.user_id))
    stranger = await join(JoinProWaitlistCommand(user_id=UserId(new_id())))

    assert (first, second, stranger) == (
        WaitlistOutcome.JOINED,
        WaitlistOutcome.ALREADY,
        WaitlistOutcome.NO_PROFILE,
    )
    assert profiles.saved == 1
