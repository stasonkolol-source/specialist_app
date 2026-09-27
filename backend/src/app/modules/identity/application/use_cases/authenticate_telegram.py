"""Вход из Mini App по проверенному initData (ADR-0009, ARCHITECTURE §8.2)."""

from dataclasses import dataclass

from app.modules.identity.api import Action
from app.modules.identity.application.access import ensure_allowed
from app.modules.identity.application.config import IdentityConfig
from app.modules.identity.application.dto import AuthResult, TelegramProfile
from app.modules.identity.application.ports import (
    AccessTokenIssuer,
    IdentityQuery,
    SessionRepository,
    UserRepository,
)
from app.modules.identity.application.tokens import issue_tokens
from app.modules.identity.domain.session import Session, SessionId
from app.modules.identity.domain.user import (
    AuthProvider,
    User,
    clean_display_name,
    locale_from_language,
)
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import new_id
from app.platform.kernel.principal import Platform
from app.platform.security.refresh import RefreshToken

AMR_TELEGRAM_WEBAPP = ("tg_webapp",)


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthenticateTelegramCommand:
    profile: TelegramProfile
    platform: Platform = Platform.TMA


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
        subject = str(profile.id)
        session_id = SessionId(new_id())
        refresh = RefreshToken.new(session_id.hex)
        async with self._uow:
            user = await self._users.find_by_identity(AuthProvider.TELEGRAM, subject)
            is_new = user is None
            if user is None:
                user = User.register(
                    provider=AuthProvider.TELEGRAM,
                    subject=subject,
                    profile=profile.snapshot(),
                    display_name=clean_display_name(profile.first_name, profile.last_name),
                    ui_locale=locale_from_language(profile.language_code),
                    now=now,
                )
                await self._users.add(user)
            else:
                ensure_allowed(await self._query.restrictions(user.id, now), Action.LOGIN, now)
                user.record_login(
                    provider=AuthProvider.TELEGRAM,
                    subject=subject,
                    profile=profile.snapshot(),
                    now=now,
                )
                await self._users.save(user)
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
        tokens = issue_tokens(
            self._issuer, user=user, session=session, refresh=refresh, roles=roles
        )
        return AuthResult(tokens=tokens, is_new=is_new)
