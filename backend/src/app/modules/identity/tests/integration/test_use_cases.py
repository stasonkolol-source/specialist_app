"""Use cases identity на PostgreSQL в откатываемой транзакции (DEVELOPMENT_PLAN 0.15a)."""

from datetime import timedelta
from uuid import UUID

import procrastinate
import pytest
from sqlalchemy import select, text
from tests.plugins.database import make_uow

from app.modules.identity.api import Action
from app.modules.identity.application.dto import AuthResult
from app.modules.identity.application.use_cases.accept_consents import AcceptConsentsCommand
from app.modules.identity.application.use_cases.authenticate_telegram import (
    AuthenticateTelegram,
    AuthenticateTelegramCommand,
)
from app.modules.identity.application.use_cases.logout import LogoutCommand
from app.modules.identity.application.use_cases.refresh_session import RefreshSessionCommand
from app.modules.identity.domain.restriction import RestrictionKind
from app.modules.identity.domain.session import RevokeReason, SessionId
from app.modules.identity.domain.user import AuthProvider, UserStatus
from app.modules.identity.errors import AccountDeletedError, SessionNotFoundError
from app.modules.identity.infrastructure.models import SessionRow
from app.modules.identity.infrastructure.repositories import (
    SqlSessionRepository,
    SqlUserRepository,
)
from app.platform.contracts.events.identity import UserRegistered
from app.platform.db.platform_tables import audit_log
from app.platform.kernel.errors import RestrictedError
from app.platform.kernel.ids import UserId, new_id
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Platform, Role
from app.platform.queue.dispatcher import EventRegistry
from app.platform.queue.port import TaskRef
from app.platform.security.errors import InvalidRefreshTokenError, SessionRevokedError
from app.platform.security.refresh import RefreshToken

from .conftest import CONFIG, Identity, telegram_profile

pytestmark = pytest.mark.integration


async def login(identity: Identity, **profile: object) -> AuthResult:
    return await identity.authenticate(
        AuthenticateTelegramCommand(profile=telegram_profile(**profile))
    )


async def session_row(identity: Identity, session_id: SessionId) -> SessionRow:
    stmt = (
        select(SessionRow)
        .where(SessionRow.id == session_id)
        .execution_options(populate_existing=True)
    )
    row = (await identity.session.execute(stmt)).scalar_one()
    await identity.session.commit()
    return row


# --- AuthenticateTelegram -----------------------------------------------------------------


async def test_first_login_registers_user_and_opens_session(identity: Identity) -> None:
    profile = telegram_profile(language_code="sr")
    result = await identity.authenticate(AuthenticateTelegramCommand(profile=profile))

    assert result.is_new
    tokens = result.tokens
    claims = identity.tokens.decode(tokens.access_token)
    assert claims.user_id == tokens.user_id
    assert claims.session_id == tokens.session_id.hex
    assert claims.platform is Platform.TMA
    assert claims.amr == ("tg_webapp",)
    assert claims.trust_level == 0
    assert claims.roles == frozenset()
    assert RefreshToken.parse(tokens.refresh_token).session_id == tokens.session_id.hex
    assert tokens.refresh_expires_at == identity.clock.now() + timedelta(days=7)

    async with identity.uow:
        user = await identity.users.get(tokens.user_id)
    assert user.display_name == "Ana Petrović"
    assert user.ui_locale is Locale.SR_LATN
    identity_row = user.identity(AuthProvider.TELEGRAM, str(profile.id))
    assert identity_row.profile["username"] == "ana_ns"
    row = await session_row(identity, tokens.session_id)
    assert row.bot_id == 7000000001
    assert row.refresh_token_hash == RefreshToken.parse(tokens.refresh_token).hash


async def test_registration_event_reaches_subscribers_in_same_transaction(
    identity: Identity, procrastinate_app: procrastinate.App
) -> None:
    on_registered = TaskRef("test.on_user_registered", UserRegistered)
    registry = EventRegistry()
    registry.subscribe(UserRegistered, on_registered)
    uow = make_uow(identity.session, procrastinate_app, registry)
    authenticate = AuthenticateTelegram(
        uow,
        SqlUserRepository(identity.session, uow),
        SqlSessionRepository(identity.session, uow),
        identity.query,
        identity.deleted,
        identity.tokens,
        CONFIG,
        identity.clock,
        identity.access,
    )
    result = await authenticate(AuthenticateTelegramCommand(profile=telegram_profile()))
    await authenticate(AuthenticateTelegramCommand(profile=telegram_profile()))

    rows: list[str | None] = list(
        (
            await identity.session.execute(
                text(
                    "SELECT args->'payload'->>'user_id' FROM procrastinate_jobs"
                    " WHERE task_name = :name AND args->'payload'->>'user_id' = :user_id"
                ),
                {"name": on_registered.name, "user_id": str(result.tokens.user_id)},
            )
        )
        .scalars()
        .all()
    )
    assert rows == [str(result.tokens.user_id)]


async def test_second_login_reuses_account_and_updates_profile(identity: Identity) -> None:
    first = await login(identity, id=880000001, username="old")
    identity.clock.advance(timedelta(days=1))
    second = await login(identity, id=880000001, username="new")

    assert not second.is_new
    assert second.tokens.user_id == first.tokens.user_id
    assert second.tokens.session_id != first.tokens.session_id
    async with identity.uow:
        user = await identity.users.get(first.tokens.user_id)
    assert user.identity(AuthProvider.TELEGRAM, "880000001").profile["username"] == "new"
    assert user.last_seen_at == identity.clock.now()


async def test_repeated_login_answers_profile_without_writing(identity: Identity) -> None:
    """Вход отдаёт профиль и «что можно» из своей транзакции — те же, что прочитал бы GET /me;
    неизменный снимок через 5 минут не пишется, и версия (ETag S31) не растёт."""
    first = await login(identity, id=880000011)
    identity.clock.advance(timedelta(minutes=5))
    second = await login(identity, id=880000011)
    user_id = first.tokens.user_id

    assert second.me == await identity.query.me(user_id)
    assert second.access == await identity.access.view(user_id)
    assert second.me.version == first.me.version
    async with identity.uow:
        user = await identity.users.get(user_id)
    assert user.version == first.me.version


async def test_staff_roles_go_to_access_token(identity: Identity) -> None:
    first = await login(identity, id=880000002)
    await identity.grant(first.tokens.user_id, Role.MODERATOR)
    again = await login(identity, id=880000002)
    assert identity.tokens.decode(again.tokens.access_token).roles == {Role.MODERATOR}


@pytest.mark.parametrize("kind", [RestrictionKind.BANNED, RestrictionKind.SUSPENDED])
async def test_banned_user_cannot_log_in(identity: Identity, kind: RestrictionKind) -> None:
    first = await login(identity, id=880000003)
    await identity.restrict(first.tokens.user_id, kind)
    with pytest.raises(RestrictedError) as caught:
        await login(identity, id=880000003)
    assert caught.value.restriction == kind.value


async def test_posting_block_does_not_prevent_login(identity: Identity) -> None:
    first = await login(identity, id=880000004)
    await identity.restrict(first.tokens.user_id, RestrictionKind.POSTING_BLOCKED)
    assert not (await login(identity, id=880000004)).is_new


async def test_deleted_account_cannot_log_in(identity: Identity) -> None:
    first = await login(identity, id=880000005)
    async with identity.uow:
        user = await identity.users.get(first.tokens.user_id)
        user.delete(by=user.id, now=identity.clock.now())
        await identity.users.save(user)
    with pytest.raises(AccountDeletedError):
        await login(identity, id=880000005)


# --- RefreshSession -----------------------------------------------------------------------


async def test_refresh_rotates_and_issues_new_access(identity: Identity) -> None:
    first = (await login(identity)).tokens
    identity.clock.advance(timedelta(minutes=20))
    second = await identity.refresh(RefreshSessionCommand(refresh_token=first.refresh_token))

    assert second.session_id == first.session_id
    assert second.refresh_token != first.refresh_token
    assert identity.tokens.decode(second.access_token).amr == ("tg_webapp",)
    third = await identity.refresh(RefreshSessionCommand(refresh_token=second.refresh_token))
    assert third.refresh_expires_at == identity.clock.now() + timedelta(days=7)


async def test_reused_refresh_revokes_chain_in_db(identity: Identity) -> None:
    stolen = (await login(identity)).tokens
    current = await identity.refresh(RefreshSessionCommand(refresh_token=stolen.refresh_token))
    identity.clock.advance(timedelta(minutes=5))

    with pytest.raises(SessionRevokedError):
        await identity.refresh(RefreshSessionCommand(refresh_token=stolen.refresh_token))
    row = await session_row(identity, stolen.session_id)
    assert row.revoked_at == identity.clock.now()
    assert row.revoke_reason is RevokeReason.REFRESH_REUSED
    assert identity.revocations.revoked == [stolen.session_id.hex]
    audit = (
        await identity.session.execute(
            select(audit_log.c.action, audit_log.c.actor_id, audit_log.c.entity_id).where(
                audit_log.c.entity_id == stolen.session_id
            )
        )
    ).all()
    assert [tuple(row) for row in audit] == [
        ("auth.refresh.reused", stolen.user_id, stolen.session_id)
    ]
    with pytest.raises(SessionRevokedError):
        await identity.refresh(RefreshSessionCommand(refresh_token=current.refresh_token))


async def test_retry_within_race_window_keeps_session(identity: Identity) -> None:
    first = (await login(identity)).tokens
    second = await identity.refresh(RefreshSessionCommand(refresh_token=first.refresh_token))
    identity.clock.advance(timedelta(seconds=2))

    with pytest.raises(InvalidRefreshTokenError):
        await identity.refresh(RefreshSessionCommand(refresh_token=first.refresh_token))
    assert (await session_row(identity, first.session_id)).revoked_at is None
    assert identity.revocations.revoked == []
    await identity.refresh(RefreshSessionCommand(refresh_token=second.refresh_token))


async def test_refresh_of_restricted_user_revokes_session(identity: Identity) -> None:
    first = (await login(identity)).tokens
    await identity.restrict(first.user_id, RestrictionKind.BANNED)
    with pytest.raises(RestrictedError):
        await identity.refresh(RefreshSessionCommand(refresh_token=first.refresh_token))
    row = await session_row(identity, first.session_id)
    assert row.revoke_reason is RevokeReason.RESTRICTED
    assert identity.revocations.revoked == [first.session_id.hex]


async def test_refresh_of_deleted_user_revokes_session(identity: Identity) -> None:
    first = (await login(identity)).tokens
    async with identity.uow:
        user = await identity.users.get(first.user_id)
        user.delete(by=user.id, now=identity.clock.now())
        await identity.users.save(user)
    with pytest.raises(AccountDeletedError):
        await identity.refresh(RefreshSessionCommand(refresh_token=first.refresh_token))
    assert (
        await session_row(identity, first.session_id)
    ).revoke_reason is RevokeReason.ACCOUNT_DELETED


async def test_refresh_after_expiry_and_for_unknown_session_fails(identity: Identity) -> None:
    first = (await login(identity)).tokens
    identity.clock.advance(timedelta(days=7))
    with pytest.raises(InvalidRefreshTokenError):
        await identity.refresh(RefreshSessionCommand(refresh_token=first.refresh_token))
    with pytest.raises(InvalidRefreshTokenError):
        await identity.refresh(
            RefreshSessionCommand(refresh_token=str(RefreshToken.new(new_id().hex)))
        )
    with pytest.raises(InvalidRefreshTokenError):
        await identity.refresh(RefreshSessionCommand(refresh_token="garbage"))  # noqa: S106


# --- Logout и фасад -----------------------------------------------------------------------


async def test_logout_revokes_own_session_only(identity: Identity) -> None:
    mine = (await login(identity)).tokens
    other = (await login(identity)).tokens
    with pytest.raises(SessionNotFoundError):
        await identity.logout(LogoutCommand(actor_id=other.user_id, session_id=mine.session_id))

    await identity.logout(LogoutCommand(actor_id=mine.user_id, session_id=mine.session_id))
    assert (await session_row(identity, mine.session_id)).revoke_reason is RevokeReason.LOGOUT
    assert identity.revocations.revoked == [mine.session_id.hex]
    with pytest.raises(SessionRevokedError):
        await identity.refresh(RefreshSessionCommand(refresh_token=mine.refresh_token))


async def test_facade_reports_user_and_restrictions(identity: Identity) -> None:
    tokens = (await login(identity, language_code="ru")).tokens
    summary = await identity.facade.get_user(tokens.user_id)
    assert summary is not None
    assert (summary.display_name, summary.ui_locale, summary.is_deleted) == (
        "Ana Petrović",
        Locale.RU,
        False,
    )
    assert await identity.facade.get_user(UserId(UUID(int=1))) is None

    await identity.accept_consents(
        AcceptConsentsCommand(
            actor_id=tokens.user_id,
            terms_version="draft-1",
            privacy_version="draft-1",
            source=Platform.TMA,
        )
    )
    await identity.facade.ensure_allowed(tokens.user_id, Action.POST)
    await identity.restrict(
        tokens.user_id,
        RestrictionKind.POSTING_BLOCKED,
        ends_at=identity.clock.now() + timedelta(days=3),
    )
    with pytest.raises(RestrictedError) as caught:
        await identity.facade.ensure_allowed(tokens.user_id, Action.POST)
    assert caught.value.until == identity.clock.now() + timedelta(days=3)
    await identity.facade.ensure_allowed(tokens.user_id, Action.MESSAGE)


async def test_user_status_is_active_after_login(identity: Identity) -> None:
    tokens = (await login(identity)).tokens
    async with identity.uow:
        user = await identity.users.get(tokens.user_id)
    assert user.status is UserStatus.ACTIVE
