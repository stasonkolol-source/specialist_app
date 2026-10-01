"""Удаление аккаунта (DEVELOPMENT_PLAN 2.12a, ARCHITECTURE §7.10): запрос с grace-периодом 7
дней и отмена, исполнение со сдвигом часов, legal hold и повторная регистрация тем же
Telegram — по хэшу, без возврата данных."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.modules.identity.application.use_cases.authenticate_telegram import (
    AuthenticateTelegramCommand,
)
from app.modules.identity.application.use_cases.cancel_deletion import CancelDeletionCommand
from app.modules.identity.application.use_cases.process_deletions import ProcessDeletionsCommand
from app.modules.identity.application.use_cases.request_deletion import RequestDeletionCommand
from app.modules.identity.domain.deletion import DeletionSource, HashKind, identity_hash
from app.modules.identity.domain.user import DELETED_DISPLAY_NAME, User, UserStatus
from app.modules.identity.infrastructure.models import AuthIdentityRow, DeletedIdentityHashRow
from app.platform.contracts.events.identity import UserDeleted, UserRegistered
from app.platform.kernel.ids import UserId
from app.platform.queue.dispatcher import EventRegistry
from app.platform.queue.port import TaskRef
from app.platform.testing.queue import queued_tasks

from .conftest import CONFIG, Identity, telegram_profile

pytestmark = pytest.mark.integration

ON_DELETED = TaskRef("test.on_user_deleted", UserDeleted)
ON_REGISTERED = TaskRef("test.on_user_registered_again", UserRegistered)
WEEK = timedelta(days=7)


async def sign_in(identity: Identity, telegram_id: int) -> UserId:
    result = await identity.authenticate(
        AuthenticateTelegramCommand(profile=telegram_profile(id=telegram_id))
    )
    return result.tokens.user_id


async def load(identity: Identity, user_id: UserId) -> User:
    async with identity.uow:
        return await identity.users.get(user_id)


async def request(identity: Identity, user_id: UserId) -> None:
    await identity.request_deletion(
        RequestDeletionCommand(actor_id=user_id, source=DeletionSource.TMA)
    )


async def test_request_waits_seven_days_and_can_be_cancelled(identity: Identity) -> None:
    user_id = await sign_in(identity, 811000001)

    first = await identity.request_deletion(
        RequestDeletionCommand(actor_id=user_id, source=DeletionSource.TMA)
    )
    identity.clock.advance(timedelta(hours=1))
    again = await identity.request_deletion(
        RequestDeletionCommand(actor_id=user_id, source=DeletionSource.BOT)
    )

    assert first.execute_after == first.requested_at + WEEK
    assert (again.id, again.execute_after) == (first.id, first.execute_after)
    me = await identity.query.me(user_id)
    assert me is not None
    assert me.deletion_scheduled_at == first.execute_after

    assert await identity.cancel_deletion(CancelDeletionCommand(actor_id=user_id)) is True
    assert await identity.cancel_deletion(CancelDeletionCommand(actor_id=user_id)) is False
    me = await identity.query.me(user_id)
    assert me is not None
    assert me.deletion_scheduled_at is None


async def test_after_seven_days_the_account_is_anonymized(
    identity: Identity, events: EventRegistry
) -> None:
    events.subscribe(UserDeleted, ON_DELETED)
    user_id = await sign_in(identity, 811000002)
    await request(identity, user_id)

    identity.clock.advance(timedelta(days=6))
    await sign_in(identity, 811000002)  # зашёл накануне — его сессия ещё жива
    identity.clock.advance(timedelta(days=1) - timedelta(minutes=1))
    early = await identity.process_deletions(ProcessDeletionsCommand())
    assert (early.deleted, early.held) == (0, 0)

    identity.clock.advance(timedelta(minutes=1))
    report = await identity.process_deletions(ProcessDeletionsCommand())

    assert report.deleted == 1
    user = await load(identity, user_id)
    assert (user.status, user.display_name, user.identities) == (
        UserStatus.DELETED,
        DELETED_DISPLAY_NAME,
        [],
    )
    logins = await identity.session.scalar(
        select(func.count()).select_from(AuthIdentityRow).where(AuthIdentityRow.user_id == user_id)
    )
    assert logins == 0
    digest = identity_hash(CONFIG.hash_key, HashKind.TELEGRAM, "811000002")
    stored = await identity.session.scalar(
        select(func.count())
        .select_from(DeletedIdentityHashRow)
        .where(DeletedIdentityHashRow.hash == digest)
    )
    assert stored == 1
    assert len(identity.revocations.revoked) == 1  # живая сессия отозвана, истёкшая — нет
    assert await identity.query.me(user_id) is None
    deleted = await queued_tasks(identity.session, ON_DELETED.name)
    assert [task.payload["user_id"] for task in deleted] == [str(user_id)]
    # исполненный запрос второй раз не исполняется
    assert (await identity.process_deletions(ProcessDeletionsCommand())).deleted == 0


async def test_open_case_holds_the_deletion(identity: Identity) -> None:
    user_id = await sign_in(identity, 811000003)
    await request(identity, user_id)
    identity.hold.users.add(user_id)
    identity.clock.advance(WEEK)

    held = await identity.process_deletions(ProcessDeletionsCommand())

    assert (held.deleted, held.held) == (0, 1)
    assert (await load(identity, user_id)).status is UserStatus.ACTIVE
    identity.hold.users.clear()
    assert (await identity.process_deletions(ProcessDeletionsCommand())).deleted == 1


async def test_same_telegram_registers_anew_and_is_flagged(
    identity: Identity, events: EventRegistry
) -> None:
    events.subscribe(UserRegistered, ON_REGISTERED)
    old = await sign_in(identity, 811000004)
    await request(identity, old)
    identity.clock.advance(WEEK)
    await identity.process_deletions(ProcessDeletionsCommand())

    new = await sign_in(identity, 811000004)

    assert new != old
    registered = [
        task.payload
        for task in await queued_tasks(identity.session, ON_REGISTERED.name)
        if task.payload["user_id"] == str(new)
    ]
    assert registered[0]["reregistered"] is True
    assert registered[0]["had_sanctions"] is False
    # через 12 месяцев хэш истекает — регистрация больше не повторная
    identity.clock.advance(timedelta(days=366))
    await request(identity, new)
    identity.clock.advance(WEEK)
    await identity.process_deletions(ProcessDeletionsCommand())
    identity.clock.advance(timedelta(days=366))
    fresh = await sign_in(identity, 811000004)
    payloads = [
        task.payload
        for task in await queued_tasks(identity.session, ON_REGISTERED.name)
        if task.payload["user_id"] == str(fresh)
    ]
    assert payloads[0]["reregistered"] is False
