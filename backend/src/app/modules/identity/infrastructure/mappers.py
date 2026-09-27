"""Маппинг строк ORM ⇄ агрегаты identity (ADR-0020 §5)."""

from app.modules.identity.domain.session import Session, SessionId
from app.modules.identity.domain.user import AuthIdentity, User
from app.modules.identity.infrastructure.models import AuthIdentityRow, SessionRow, UserRow
from app.platform.kernel.ids import UserId


def user_to_domain(row: UserRow) -> User:
    return User(
        id=UserId(row.id),
        status=row.status,
        display_name=row.display_name,
        ui_locale=row.ui_locale,
        timezone=row.timezone,
        trust_level=row.trust_level,
        created_at=row.created_at,
        identities=[
            AuthIdentity(
                id=i.id,
                provider=i.provider,
                subject=i.subject,
                profile=dict(i.profile),
                created_at=i.created_at,
                last_login_at=i.last_login_at,
            )
            for i in row.identities
        ],
        phone_e164=row.phone_e164,
        phone_verified_at=row.phone_verified_at,
        last_seen_at=row.last_seen_at,
        deleted_at=row.deleted_at,
        version=row.version,
    )


def apply_user(user: User, row: UserRow) -> None:
    row.status = user.status
    row.display_name = user.display_name
    row.ui_locale = user.ui_locale
    row.timezone = user.timezone
    row.trust_level = user.trust_level
    row.created_at = user.created_at
    row.phone_e164 = user.phone_e164
    row.phone_verified_at = user.phone_verified_at
    row.last_seen_at = user.last_seen_at
    row.deleted_at = user.deleted_at
    by_id = {identity.id: identity for identity in row.identities}
    for identity in user.identities:
        target = by_id.get(identity.id)
        if target is None:
            target = AuthIdentityRow(id=identity.id)
            row.identities.append(target)
        target.provider = identity.provider
        target.subject = identity.subject
        target.profile = dict(identity.profile)
        target.created_at = identity.created_at
        target.last_login_at = identity.last_login_at


def session_to_domain(row: SessionRow) -> Session:
    return Session(
        id=SessionId(row.id),
        user_id=UserId(row.user_id),
        platform=row.platform,
        bot_id=row.bot_id,
        amr=tuple(row.amr),
        refresh_hash=row.refresh_token_hash,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        previous_refresh_hash=row.previous_refresh_hash,
        rotated_at=row.rotated_at,
        revoked_at=row.revoked_at,
        revoke_reason=row.revoke_reason,
    )


def apply_session(session: Session, row: SessionRow) -> None:
    row.user_id = session.user_id
    row.platform = session.platform
    row.bot_id = session.bot_id
    row.amr = list(session.amr)
    row.refresh_token_hash = session.refresh_hash
    row.previous_refresh_hash = session.previous_refresh_hash
    row.rotated_at = session.rotated_at
    row.created_at = session.created_at
    row.last_used_at = session.last_used_at
    row.expires_at = session.expires_at
    row.revoked_at = session.revoked_at
    row.revoke_reason = session.revoke_reason
