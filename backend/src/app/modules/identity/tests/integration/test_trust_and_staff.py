"""Уровень доверия, отзыв сессий при бане и роли персонала (DEVELOPMENT_PLAN 2.5a).

Use cases и фасад на PostgreSQL в откатываемой транзакции, часы — FakeClock: «14 дней без
нарушений» проверяются сдвигом часов.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select, text

from app.modules.identity.api import RestrictionIn
from app.modules.identity.application.use_cases import age_trust_levels
from app.modules.identity.application.use_cases.age_trust_levels import AgeTrustLevelsCommand
from app.modules.identity.application.use_cases.authenticate_telegram import (
    AuthenticateTelegramCommand,
)
from app.modules.identity.application.use_cases.grant_staff_role import GrantStaffRoleCommand
from app.modules.identity.application.use_cases.revoke_restricted_sessions import (
    RevokeRestrictedSessionsCommand,
)
from app.modules.identity.domain.restriction import RestrictionKind
from app.modules.identity.domain.trust import TrustLevel
from app.modules.identity.infrastructure.models import SessionRow, UserRow
from app.platform.kernel.ids import UserId
from app.platform.kernel.principal import Role

from .conftest import Identity, telegram_profile

pytestmark = pytest.mark.integration

FORTNIGHT = timedelta(days=14)


async def registered(identity: Identity, telegram_id: int | None = None) -> UserId:
    profile = telegram_profile(id=telegram_id) if telegram_id else telegram_profile()
    result = await identity.authenticate(AuthenticateTelegramCommand(profile=profile))
    return result.tokens.user_id


async def level(identity: Identity, user_id: UserId) -> int:
    u = UserRow.__table__.c
    value: int = (
        await identity.session.execute(select(u.trust_level).where(u.id == user_id))
    ).scalar_one()
    return value


async def age(identity: Identity) -> int:
    return await identity.age_trust_levels(AgeTrustLevelsCommand())


async def test_fourteen_clean_days_give_level_one(identity: Identity) -> None:
    user_id = await registered(identity)

    identity.clock.advance(FORTNIGHT - timedelta(minutes=1))
    await age(identity)
    assert await level(identity, user_id) == TrustLevel.NEW
    identity.clock.advance(timedelta(minutes=1))
    assert await age(identity) >= 1  # в общей БД есть и пользователи других тестов
    assert await level(identity, user_id) == TrustLevel.BASIC


async def test_violation_drops_the_level_for_fourteen_days(identity: Identity) -> None:
    user_id = await registered(identity)
    identity.clock.advance(timedelta(days=30))
    await age(identity)
    assert await level(identity, user_id) == TrustLevel.BASIC

    async with identity.uow:
        await identity.facade.record_violation(user_id)  # предупреждение или жалоба
    assert await level(identity, user_id) == TrustLevel.NEW

    identity.clock.advance(FORTNIGHT - timedelta(hours=1))
    await age(identity)
    assert await level(identity, user_id) == TrustLevel.NEW
    identity.clock.advance(timedelta(hours=1))
    await age(identity)
    assert await level(identity, user_id) == TrustLevel.BASIC


async def test_level_stays_zero_while_a_sanction_is_in_force(identity: Identity) -> None:
    user_id = await registered(identity)
    identity.clock.advance(timedelta(days=30))
    await age(identity)

    async with identity.uow:
        await identity.facade.restrict(
            RestrictionIn(
                user_id=user_id,
                kind=RestrictionKind.RESPONDING_BLOCKED,
                reason_code="spam_ad",
                ends_at=identity.clock.now() + timedelta(days=30),
            )
        )
    assert await level(identity, user_id) == TrustLevel.NEW

    identity.clock.advance(timedelta(days=20))  # 14 дней прошли, но санкция действует
    await age(identity)
    assert await level(identity, user_id) == TrustLevel.NEW
    identity.clock.advance(timedelta(days=10))  # санкция кончилась
    await age(identity)
    assert await level(identity, user_id) == TrustLevel.BASIC


async def test_trust_aging_goes_through_every_candidate(
    identity: Identity, monkeypatch: pytest.MonkeyPatch
) -> None:
    users = [await registered(identity) for _ in range(3)]
    identity.clock.advance(FORTNIGHT)
    monkeypatch.setattr(age_trust_levels, "CHUNK", 2)  # несколько порций по (created_at, id)

    await age(identity)

    assert [await level(identity, user_id) for user_id in users] == [TrustLevel.BASIC] * 3


async def test_ban_revokes_every_session_at_once(identity: Identity) -> None:
    user_id = await registered(identity)
    other = await registered(identity)  # чужая сессия остаётся
    sessions = SessionRow.__table__.c

    assert (
        await identity.revoke_restricted_sessions(
            RevokeRestrictedSessionsCommand(user_id=user_id, kind=RestrictionKind.LIMITED)
        )
        == 0
    )
    revoked = await identity.revoke_restricted_sessions(
        RevokeRestrictedSessionsCommand(user_id=user_id, kind=RestrictionKind.BANNED)
    )

    assert revoked == 1
    rows = (
        await identity.session.execute(
            select(sessions.user_id, sessions.revoke_reason).where(
                sessions.user_id.in_([user_id, other]), sessions.revoked_at.is_not(None)
            )
        )
    ).all()
    assert [tuple(row) for row in rows] == [(user_id, "restricted")]
    assert len(identity.revocations.revoked) == 1  # и access-токены — через denylist
    assert (
        await identity.revoke_restricted_sessions(
            RevokeRestrictedSessionsCommand(user_id=user_id, kind=RestrictionKind.BANNED)
        )
        == 0
    )


async def test_staff_role_is_granted_once_and_audited(identity: Identity) -> None:
    telegram_id = 700_100_200
    user_id = await registered(identity, telegram_id)

    assert (
        await identity.grant_staff_role(GrantStaffRoleCommand(telegram_id=1, role=Role.ADMIN))
        is None
    )
    granted = await identity.grant_staff_role(
        GrantStaffRoleCommand(telegram_id=telegram_id, role=Role.MODERATOR)
    )
    again = await identity.grant_staff_role(
        GrantStaffRoleCommand(telegram_id=telegram_id, role=Role.MODERATOR)
    )

    assert granted is not None
    assert (granted.user_id, granted.granted) == (user_id, True)
    assert again is not None
    assert not again.granted
    assert await identity.query.roles(user_id) == frozenset({Role.MODERATOR})
    audit = (
        await identity.session.execute(
            text(
                "SELECT action, actor_kind, changes FROM platform.audit_log"
                " WHERE entity_id = :id ORDER BY id"
            ),
            {"id": user_id},
        )
    ).all()
    assert [tuple(row) for row in audit] == [
        ("identity.role.granted", "system", {"role": "moderator"})
    ]
