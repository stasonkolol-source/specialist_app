"""Сборка модуля identity для dishka (ADR-0020 §7)."""

from datetime import timedelta

from dishka import Provider, Scope, provide

from app.modules.identity.api import IdentityApi
from app.modules.identity.application.access import AccessChecker
from app.modules.identity.application.config import IdentityConfig
from app.modules.identity.application.facade import IdentityFacade
from app.modules.identity.application.ports import (
    AccessTokenIssuer,
    ConsentRepository,
    DeletedIdentities,
    DeletionRepository,
    IdentityQuery,
    RestrictionRepository,
    RoleRepository,
    SessionRepository,
    SessionRevocations,
    UserRepository,
)
from app.modules.identity.application.trust import TrustRecalculation
from app.modules.identity.application.use_cases.accept_consents import AcceptConsents
from app.modules.identity.application.use_cases.age_trust_levels import AgeTrustLevels
from app.modules.identity.application.use_cases.authenticate_telegram import AuthenticateTelegram
from app.modules.identity.application.use_cases.cancel_deletion import CancelDeletion
from app.modules.identity.application.use_cases.grant_staff_role import GrantStaffRole
from app.modules.identity.application.use_cases.logout import Logout
from app.modules.identity.application.use_cases.process_deletions import ProcessDeletions
from app.modules.identity.application.use_cases.refresh_session import RefreshSession
from app.modules.identity.application.use_cases.register_telegram_user import (
    RegisterTelegramUser,
)
from app.modules.identity.application.use_cases.request_deletion import RequestDeletion
from app.modules.identity.application.use_cases.reset_onboarding import ResetOnboarding
from app.modules.identity.application.use_cases.revoke_restricted_sessions import (
    RevokeRestrictedSessions,
)
from app.modules.identity.application.use_cases.update_profile import UpdateProfile
from app.modules.identity.infrastructure.deletion import (
    SqlDeletedIdentities,
    SqlDeletionRepository,
)
from app.modules.identity.infrastructure.queries import SqlIdentityQuery
from app.modules.identity.infrastructure.repositories import (
    SqlConsentRepository,
    SqlRestrictionRepository,
    SqlRoleRepository,
    SqlSessionRepository,
    SqlUserRepository,
)
from app.platform.security.denylist import SessionDenylist
from app.platform.security.jwt import AccessTokens
from app.platform.settings import AppSettings, JwtSettings, TelegramSettings


def bot_id_of(token: str) -> int | None:
    """id бота — число до двоеточия в токене BotFather."""
    head = token.split(":", 1)[0]
    return int(head) if head.isdigit() else None


DEV_HASH_KEY = b"sosed-dev-hash-key"
"""Ключ HMAC хэшей удалённых аккаунтов без APP_HASH_KEY — только dev и тесты."""


class IdentityProvider(Provider):
    """Провайдер модуля identity: связывает порты с реализациями."""

    scope = Scope.REQUEST

    @provide(scope=Scope.APP)
    def config(
        self, app: AppSettings, telegram: TelegramSettings, jwt: JwtSettings
    ) -> IdentityConfig:
        return IdentityConfig(
            bot_id=bot_id_of(telegram.bot_token.get_secret_value()),
            refresh_ttl_tma=timedelta(days=jwt.refresh_ttl_days_tma),
            refresh_ttl_mobile=timedelta(days=jwt.refresh_ttl_days),
            # на stage и проде ключ обязателен (Settings); dev и тесты — ключ разработки
            hash_key=app.hash_key.get_secret_value().encode() if app.hash_key else DEV_HASH_KEY,
        )

    @provide(scope=Scope.APP)
    def issuer(self, tokens: AccessTokens) -> AccessTokenIssuer:
        return tokens

    @provide(scope=Scope.APP)
    def revocations(self, denylist: SessionDenylist) -> SessionRevocations:
        return denylist

    users = provide(SqlUserRepository, provides=UserRepository)
    sessions = provide(SqlSessionRepository, provides=SessionRepository)
    consents = provide(SqlConsentRepository, provides=ConsentRepository)
    restrictions = provide(SqlRestrictionRepository, provides=RestrictionRepository)
    roles = provide(SqlRoleRepository, provides=RoleRepository)
    query = provide(SqlIdentityQuery, provides=IdentityQuery)
    access = provide(AccessChecker)
    trust = provide(TrustRecalculation)
    facade = provide(IdentityFacade, provides=IdentityApi)
    authenticate_telegram = provide(AuthenticateTelegram)
    refresh_session = provide(RefreshSession)
    logout = provide(Logout)
    update_profile = provide(UpdateProfile)
    accept_consents = provide(AcceptConsents)
    register_telegram_user = provide(RegisterTelegramUser)
    reset_onboarding = provide(ResetOnboarding)
    age_trust_levels = provide(AgeTrustLevels)
    revoke_restricted_sessions = provide(RevokeRestrictedSessions)
    deletions = provide(SqlDeletionRepository, provides=DeletionRepository)
    deleted_identities = provide(SqlDeletedIdentities, provides=DeletedIdentities)
    request_deletion = provide(RequestDeletion)
    cancel_deletion = provide(CancelDeletion)
    process_deletions = provide(ProcessDeletions)
    grant_staff_role = provide(GrantStaffRole)
