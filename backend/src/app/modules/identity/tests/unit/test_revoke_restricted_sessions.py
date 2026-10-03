"""Задержавшийся отзыв по санкции не затрагивает сессии после её снятия."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.modules.identity.application.ports import (
    IdentityQuery,
    SessionRepository,
    SessionRevocations,
)
from app.modules.identity.application.use_cases.revoke_restricted_sessions import (
    RevokeRestrictedSessions,
)
from app.modules.identity.domain.restriction import Restriction
from app.modules.identity.domain.session import RevokeReason, Session
from app.modules.identity.tasks import revoke_restricted_sessions
from app.platform.contracts.events.identity import RestrictionKind, UserRestricted
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import RestrictionId, UserId, new_id
from app.platform.kernel.principal import Platform
from app.platform.testing.clock import FakeClock

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


@pytest.mark.parametrize("kind", [RestrictionKind.BANNED, RestrictionKind.SUSPENDED])
@pytest.mark.parametrize("still_restricted", [False, True])
async def test_delayed_restriction_preserves_new_sessions(
    kind: RestrictionKind, still_restricted: bool
) -> None:
    user_id = UserId(new_id())
    sessions = [
        Session.open(
            user_id=user_id,
            platform=Platform.TMA,
            bot_id=7000000001,
            amr=("tg_webapp",),
            refresh_hash=b"test-hash",
            now=created_at,
            ttl=timedelta(days=7),
        )
        for created_at in (NOW - timedelta(hours=1), NOW, NOW + timedelta(hours=2))
    ]
    repository = AsyncMock(spec=SessionRepository)
    repository.active_for_user.side_effect = lambda *_: [
        session for session in sessions if session.revoked_at is None
    ]
    revocations = AsyncMock(spec=SessionRevocations)
    query = AsyncMock(spec=IdentityQuery)
    query.restrictions.return_value = (
        [Restriction.impose(kind=kind, reason_code="spam", now=NOW)] if still_restricted else []
    )
    revoke = RevokeRestrictedSessions(
        AsyncMock(spec=UnitOfWork),
        repository,
        revocations,
        FakeClock(NOW + timedelta(hours=3)),
        query,
    )
    event = UserRestricted(
        user_id=user_id,
        restriction_id=RestrictionId(new_id()),
        kind=kind,
        reason_code="spam",
        until=NOW + timedelta(hours=1),
        case_id=None,
        occurred_at=NOW,
    )

    await revoke_restricted_sessions(event, revoke)
    await revoke_restricted_sessions(event, revoke)

    expected = sessions if still_restricted else sessions[:2]
    assert (sessions[2].revoked_at is not None) is still_restricted
    assert [session.revoke_reason for session in expected] == [RevokeReason.RESTRICTED] * len(
        expected
    )
    assert [call.args[0] for call in repository.save.await_args_list] == expected
    assert [call.args[0] for call in revocations.revoke.await_args_list] == [
        session.sid for session in expected
    ]
