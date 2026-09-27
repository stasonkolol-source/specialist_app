"""Обновление пары токенов по refresh с ротацией и детектором кражи (ADR-0009)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.identity.application.config import IdentityConfig
from app.modules.identity.application.dto import SessionTokens
from app.modules.identity.application.ports import (
    AccessTokenIssuer,
    IdentityQuery,
    SessionRepository,
    SessionRevocations,
    UserRepository,
)
from app.modules.identity.application.tokens import issue_tokens
from app.modules.identity.domain.restriction import ACCOUNT_BLOCKING, blocking
from app.modules.identity.domain.session import RefreshOutcome, RevokeReason, SessionId
from app.modules.identity.domain.user import UserStatus
from app.modules.identity.errors import AccountDeletedError, SessionNotFoundError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.errors import RestrictedError
from app.platform.security.errors import InvalidRefreshTokenError, SessionRevokedError
from app.platform.security.refresh import RefreshToken


@dataclass(frozen=True, slots=True, kw_only=True)
class RefreshSessionCommand:
    refresh_token: str


class RefreshSession:
    def __init__(
        self,
        uow: UnitOfWork,
        users: UserRepository,
        sessions: SessionRepository,
        query: IdentityQuery,
        issuer: AccessTokenIssuer,
        revocations: SessionRevocations,
        config: IdentityConfig,
        clock: Clock,
    ) -> None:
        self._uow, self._users, self._sessions, self._query = uow, users, sessions, query
        self._issuer, self._revocations, self._config, self._clock = (
            issuer,
            revocations,
            config,
            clock,
        )

    async def __call__(self, cmd: RefreshSessionCommand) -> SessionTokens:
        presented = RefreshToken.parse(cmd.refresh_token)
        fresh = RefreshToken.new(presented.session_id)
        now = self._clock.now()
        refused: Exception | None = None
        async with self._uow:
            try:
                session = await self._sessions.get_for_update(
                    SessionId(UUID(hex=presented.session_id))
                )
            except SessionNotFoundError:
                raise InvalidRefreshTokenError from None
            outcome = session.refresh(
                presented_hash=presented.hash,
                new_hash=fresh.hash,
                now=now,
                ttl=self._config.refresh_ttl(session.platform),
            )
            user = await self._users.get(session.user_id)
            roles = await self._query.roles(user.id)
            restriction = blocking(
                await self._query.restrictions(user.id, now), ACCOUNT_BLOCKING, now
            )
            if outcome is RefreshOutcome.REUSED:
                refused = SessionRevokedError()
            elif user.status is UserStatus.DELETED:
                session.revoke(reason=RevokeReason.ACCOUNT_DELETED, now=now)
                refused = AccountDeletedError(user_id=user.id)
            elif restriction is not None:
                session.revoke(reason=RevokeReason.RESTRICTED, now=now)
                refused = RestrictedError(
                    restriction=restriction.kind.value, until=restriction.ends_at
                )
            await self._sessions.save(session)
        if refused is not None:
            await self._revocations.revoke(session.sid)
            raise refused
        if outcome is RefreshOutcome.RACE:
            raise InvalidRefreshTokenError
        return issue_tokens(self._issuer, user=user, session=session, refresh=fresh, roles=roles)
