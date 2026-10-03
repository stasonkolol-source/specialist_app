"""Сбой denylist не должен мешать повторному отзыву access-токенов при refresh."""

from dataclasses import dataclass, field
from datetime import timedelta

import procrastinate
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.application.config import IdentityConfig
from app.modules.identity.application.use_cases.refresh_session import (
    RefreshSession,
    RefreshSessionCommand,
)
from app.modules.identity.domain.session import RACE_WINDOW, RevokeReason, Session
from app.modules.identity.errors import AccountDeletedError
from app.modules.identity.infrastructure.queries import SqlIdentityQuery
from app.modules.identity.infrastructure.repositories import (
    SqlSessionRepository,
    SqlUserRepository,
)
from app.platform.audit.sql import SqlAuditLog
from app.platform.db.platform_tables import audit_log
from app.platform.kernel.clock import SystemClock
from app.platform.kernel.errors import RestrictedError
from app.platform.kernel.principal import Platform
from app.platform.security.errors import SessionRevokedError
from app.platform.security.jwt import AccessTokens, JwtKeys, SigningKey
from app.platform.security.refresh import RefreshToken
from app.platform.testing.clock import FakeClock
from tests.plugins.database import make_uow
from tests.plugins.identity import insert_restriction, insert_user

pytestmark = pytest.mark.integration


@dataclass
class FakeRevocations:
    unavailable: bool = True
    revoked: list[str] = field(default_factory=list)

    async def revoke(self, session_id: str) -> None:
        if self.unavailable:
            raise RedisConnectionError("denylist unavailable")
        self.revoked.append(session_id)


@pytest.mark.parametrize(
    ("reason", "error"),
    [
        (RevokeReason.REFRESH_REUSED, SessionRevokedError),
        (RevokeReason.RESTRICTED, RestrictedError),
        (RevokeReason.ACCOUNT_DELETED, AccountDeletedError),
    ],
)
async def test_refresh_retries_revocation_after_denylist_failure(
    db_session: AsyncSession,
    procrastinate_app: procrastinate.App,
    reason: RevokeReason,
    error: type[Exception],
) -> None:
    clock = FakeClock(SystemClock().now())
    uow = make_uow(db_session, procrastinate_app)
    users = SqlUserRepository(db_session, uow)
    sessions = SqlSessionRepository(db_session, uow)
    user_id = await insert_user(db_session)
    config = IdentityConfig(
        bot_id=7000000001,
        refresh_ttl_tma=timedelta(days=7),
        refresh_ttl_mobile=timedelta(days=30),
        hash_key=b"test-hash-key",
    )
    session = Session.open(
        user_id=user_id,
        platform=Platform.TMA,
        bot_id=config.bot_id,
        amr=("tg_webapp",),
        refresh_hash=b"",
        now=clock.now(),
        ttl=config.refresh_ttl_tma,
    )
    presented = RefreshToken.new(session.sid)
    session.refresh_hash = presented.hash
    if reason is RevokeReason.REFRESH_REUSED:
        session.refresh(
            presented_hash=presented.hash,
            new_hash=RefreshToken.new(session.sid).hash,
            now=clock.now(),
            ttl=config.refresh_ttl_tma,
        )
        clock.advance(RACE_WINDOW + timedelta(seconds=1))
    async with uow:
        await sessions.add(session)
        if reason is RevokeReason.ACCOUNT_DELETED:
            user = await users.get(user_id)
            user.delete(by=user_id, now=clock.now())
            await users.save(user)
    if reason is RevokeReason.RESTRICTED:
        await insert_restriction(db_session, user_id, "banned")

    revocations = FakeRevocations()
    refresh = RefreshSession(
        uow,
        users,
        sessions,
        SqlIdentityQuery(db_session),
        AccessTokens(
            JwtKeys.of(SigningKey.generate("test")),
            clock,
            issuer="sosed",
            ttl=timedelta(minutes=15),
        ),
        revocations,
        SqlAuditLog(db_session, uow),
        config,
        clock,
    )
    command = RefreshSessionCommand(refresh_token=str(presented))
    with pytest.raises(RedisConnectionError):
        await refresh(command)

    async with uow:
        unchanged = await sessions.get_for_update(session.id)
    assert unchanged.revoked_at is None
    assert unchanged.refresh_hash == session.refresh_hash
    assert unchanged.previous_refresh_hash == session.previous_refresh_hash
    assert unchanged.expires_at == session.expires_at
    assert revocations.revoked == []

    revocations.unavailable = False
    with pytest.raises(error):
        await refresh(command)

    async with uow:
        revoked = await sessions.get_for_update(session.id)
    assert revoked.revoke_reason is reason
    assert revoked.revoked_at == clock.now()
    assert revocations.revoked == [session.sid]
    audit_count = await db_session.scalar(
        select(func.count()).select_from(audit_log).where(audit_log.c.entity_id == session.id)
    )
    assert audit_count == (1 if reason is RevokeReason.REFRESH_REUSED else 0)
