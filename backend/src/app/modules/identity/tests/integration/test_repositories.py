"""Репозитории identity: round-trip агрегатов и перевод ограничений (ADR-0020 §5, §11)."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.modules.identity.domain.session import RevokeReason, Session, SessionId
from app.modules.identity.domain.user import AuthProvider, User
from app.modules.identity.errors import (
    ConcurrentLoginError,
    SessionNotFoundError,
    UserNotFoundError,
)
from app.modules.identity.infrastructure.models import StatusHistoryRow
from app.platform.kernel.ids import UserId, new_id
from app.platform.kernel.localized import Locale
from app.platform.kernel.principal import Platform
from app.platform.testing.assertions import assert_same_state

from .conftest import Identity

pytestmark = pytest.mark.integration


def new_user(identity: Identity, subject: str | None = None) -> User:
    return User.register(
        provider=AuthProvider.TELEGRAM,
        subject=subject or str(new_id().int % 10**12),
        profile={"first_name": "Ana", "is_premium": True},
        display_name="Ana",
        ui_locale=Locale.SR_LATN,
        now=identity.clock.now(),
    )


async def test_user_roundtrip_keeps_state(identity: Identity) -> None:
    user = new_user(identity)
    async with identity.uow:
        await identity.users.add(user)
    async with identity.uow:
        loaded = await identity.users.get(user.id)
    user.pull_events()
    assert_same_state(user, loaded)


async def test_save_bumps_version_and_writes_status_history(identity: Identity) -> None:
    user = new_user(identity)
    async with identity.uow:
        await identity.users.add(user)
    async with identity.uow:
        loaded = await identity.users.get(user.id)
        loaded.record_login(
            provider=AuthProvider.TELEGRAM,
            subject=loaded.identities[0].subject,
            profile={"first_name": "Anna"},
            now=identity.clock.advance(timedelta(hours=1)),
        )
        await identity.users.save(loaded)
    assert loaded.version == 2
    async with identity.uow:
        again = await identity.users.get(user.id)
        again.delete(by=again.id, now=identity.clock.now(), reason="user_request")
        await identity.users.save(again)
    async with identity.uow:
        reloaded = await identity.users.get(user.id)
        history = (
            (
                await identity.session.execute(
                    select(StatusHistoryRow.to_status).where(StatusHistoryRow.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
    assert reloaded.version == 3
    assert reloaded.identities[0].profile == {"first_name": "Anna"}
    assert history == ["deleted"]


async def test_find_by_identity(identity: Identity) -> None:
    user = new_user(identity, subject="555000111")
    async with identity.uow:
        await identity.users.add(user)
    async with identity.uow:
        found = await identity.users.find_by_identity(AuthProvider.TELEGRAM, "555000111")
        missing = await identity.users.find_by_identity(AuthProvider.APPLE, "555000111")
    assert found is not None
    assert found.id == user.id
    assert missing is None


async def test_same_telegram_account_twice_is_concurrent_login(identity: Identity) -> None:
    async with identity.uow:
        await identity.users.add(new_user(identity, subject="777000111"))
    with pytest.raises(ConcurrentLoginError):
        async with identity.uow:
            await identity.users.add(new_user(identity, subject="777000111"))


async def test_unknown_ids_raise_not_found(identity: Identity) -> None:
    async with identity.uow:
        with pytest.raises(UserNotFoundError):
            await identity.users.get(UserId(new_id()))
    async with identity.uow:
        with pytest.raises(SessionNotFoundError):
            await identity.sessions.get_for_update(SessionId(new_id()))


async def test_session_roundtrip_and_revoke(identity: Identity) -> None:
    user = new_user(identity)
    session = Session.open(
        user_id=user.id,
        platform=Platform.TMA,
        bot_id=7000000001,
        amr=("tg_webapp",),
        refresh_hash=b"\x01" * 32,
        now=identity.clock.now(),
        ttl=timedelta(days=7),
    )
    async with identity.uow:
        await identity.users.add(user)
        await identity.sessions.add(session)
    async with identity.uow:
        loaded = await identity.sessions.get_for_update(session.id)
        assert_same_state(session, loaded)
        loaded.revoke(reason=RevokeReason.LOGOUT, now=identity.clock.now())
        await identity.sessions.save(loaded)
    async with identity.uow:
        again = await identity.sessions.get_for_update(session.id)
    assert again.revoke_reason is RevokeReason.LOGOUT


async def test_user_table_has_one_row_per_registration(identity: Identity) -> None:
    from app.modules.identity.infrastructure.models import UserRow

    before = (
        await identity.session.execute(select(func.count()).select_from(UserRow))
    ).scalar_one()
    async with identity.uow:
        await identity.users.add(new_user(identity))
    after = (await identity.session.execute(select(func.count()).select_from(UserRow))).scalar_one()
    assert after == before + 1
