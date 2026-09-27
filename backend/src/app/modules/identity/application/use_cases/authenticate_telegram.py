"""Вход из Mini App по проверенному initData (ADR-0009, ARCHITECTURE §8.2)."""

from dataclasses import dataclass

from app.modules.identity.application.config import IdentityConfig
from app.modules.identity.application.dto import AuthResult, TelegramProfile
from app.modules.identity.application.ports import (
    AccessTokenIssuer,
    IdentityQuery,
    SessionRepository,
    UserRepository,
)
from app.modules.identity.application.telegram import sign_in_telegram
from app.modules.identity.application.tokens import issue_tokens
from app.modules.identity.domain.session import Session, SessionId
from app.modules.identity.domain.user import User
from app.platform.contracts.events.identity import EntryPoint
from app.platform.db.port import UnitOfWork
from app.platform.db.retry import retry_on_conflict
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import new_id
from app.platform.kernel.principal import Platform, Role
from app.platform.security.refresh import RefreshToken

AMR_TELEGRAM_WEBAPP = ("tg_webapp",)


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthenticateTelegramCommand:
    profile: TelegramProfile
    platform: Platform = Platform.TMA
    start_param: str | None = None
    """`start_param` проверенного initData — код `startapp` (первое касание, growth)."""


class AuthenticateTelegram:
    def __init__(
        self,
        uow: UnitOfWork,
        users: UserRepository,
        sessions: SessionRepository,
        query: IdentityQuery,
        issuer: AccessTokenIssuer,
        config: IdentityConfig,
        clock: Clock,
    ) -> None:
        self._uow, self._users, self._sessions = uow, users, sessions
        self._query, self._issuer, self._config, self._clock = query, issuer, config, clock

    async def __call__(self, cmd: AuthenticateTelegramCommand) -> AuthResult:
        now = self._clock.now()
        profile = cmd.profile
        session_id = SessionId(new_id())
        refresh = RefreshToken.new(session_id.hex)

        async def attempt() -> tuple[User, bool, Session, frozenset[Role]]:
            async with self._uow:
                user, is_new = await sign_in_telegram(
                    self._users,
                    self._query,
                    profile,
                    now,
                    entry_point=EntryPoint.MINI_APP,
                    start_param=cmd.start_param,
                )
                session = Session.open(
                    session_id=session_id,
                    user_id=user.id,
                    platform=cmd.platform,
                    bot_id=self._config.bot_id,
                    amr=AMR_TELEGRAM_WEBAPP,
                    refresh_hash=refresh.hash,
                    now=now,
                    ttl=self._config.refresh_ttl(cmd.platform),
                )
                await self._sessions.add(session)
                roles = await self._query.roles(user.id)
            return user, is_new, session, roles

        # первый вход Mini App и /start одновременно: второй создатель повторяет и входит
        user, is_new, session, roles = await retry_on_conflict(attempt)
        tokens = issue_tokens(
            self._issuer, user=user, session=session, refresh=refresh, roles=roles
        )
        return AuthResult(tokens=tokens, is_new=is_new)
