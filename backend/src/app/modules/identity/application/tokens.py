"""Сборка пары токенов для клиента из пользователя и сессии."""

from app.modules.identity.application.dto import SessionTokens
from app.modules.identity.application.ports import AccessTokenIssuer
from app.modules.identity.domain.session import Session
from app.modules.identity.domain.user import User
from app.platform.kernel.principal import Principal, Role
from app.platform.security.refresh import RefreshToken


def issue_tokens(
    issuer: AccessTokenIssuer,
    *,
    user: User,
    session: Session,
    refresh: RefreshToken,
    roles: frozenset[Role],
) -> SessionTokens:
    principal = Principal(
        user_id=user.id,
        trust_level=user.trust_level,
        roles=roles,
        platform=session.platform,
        session_id=session.sid,
    )
    access, access_expires_at = issuer.issue(principal, amr=session.amr)
    return SessionTokens(
        user_id=user.id,
        session_id=session.id,
        access_token=access,
        access_expires_at=access_expires_at,
        refresh_token=str(refresh),
        refresh_expires_at=session.expires_at,
    )
