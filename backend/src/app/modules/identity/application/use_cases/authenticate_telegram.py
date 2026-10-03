"""Вход из Mini App по проверенному initData (ADR-0009, ARCHITECTURE §8.2)."""

from dataclasses import dataclass

from app.modules.identity.application.access import AccessChecker
from app.modules.identity.application.config import IdentityConfig
from app.modules.identity.application.dto import AuthResult, LoginState, MeView, TelegramProfile
from app.modules.identity.application.ports import (
    AccessTokenIssuer,
    DeletedIdentities,
    IdentityQuery,
    SessionRepository,
    UserRepository,
)
from app.modules.identity.application.telegram import SignedIn, sign_in_telegram
from app.modules.identity.application.tokens import issue_tokens
from app.modules.identity.domain.session import Session, SessionId
from app.platform.contracts.events.identity import EntryPoint
from app.platform.db.port import UnitOfWork
from app.platform.db.retry import retry_on_conflict
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import new_id
from app.platform.kernel.principal import Platform
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
        deleted: DeletedIdentities,
        issuer: AccessTokenIssuer,
        config: IdentityConfig,
        clock: Clock,
        access: AccessChecker,
    ) -> None:
        self._uow, self._users, self._sessions = uow, users, sessions
        self._query, self._deleted, self._issuer = query, deleted, issuer
        self._config, self._clock, self._access = config, clock, access

    async def __call__(self, cmd: AuthenticateTelegramCommand) -> AuthResult:
        now = self._clock.now()
        profile = cmd.profile
        session_id = SessionId(new_id())
        refresh = RefreshToken.new(session_id.hex)

        async def attempt() -> tuple[SignedIn, Session, LoginState]:
            async with self._uow:
                signed = await sign_in_telegram(
                    self._users,
                    self._query,
                    self._deleted,
                    profile,
                    now,
                    hash_key=self._config.hash_key,
                    entry_point=EntryPoint.MINI_APP,
                    start_param=cmd.start_param,
                )
                session = Session.open(
                    session_id=session_id,
                    user_id=signed.user.id,
                    platform=cmd.platform,
                    bot_id=self._config.bot_id,
                    amr=AMR_TELEGRAM_WEBAPP,
                    refresh_hash=refresh.hash,
                    now=now,
                    ttl=self._config.refresh_ttl(cmd.platform),
                )
                await self._sessions.add(session)
                # роли — в токен; согласия и ждущее удаление — в ответ (/me без чтений после
                # commit): одним запросом в той же транзакции
                state = await self._query.login_state(signed.user.id)
            return signed, session, state

        # первый вход Mini App и /start одновременно: второй создатель повторяет и входит
        signed, session, state = await retry_on_conflict(attempt)
        tokens = issue_tokens(
            self._issuer, user=signed.user, session=session, refresh=refresh, roles=state.roles
        )
        return AuthResult(
            tokens=tokens,
            is_new=signed.is_new,
            me=MeView.of(signed.user, deletion_scheduled_at=state.deletion_scheduled_at),
            access=await self._access.summary(signed.restrictions, state.consents),
        )
