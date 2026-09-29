"""Фикстуры notifications: use case канала на сессии теста (откат в конце).

Внешнее — фейки (ADR-0020 §11): фасад identity отдаёт личный чат, который задал тест.
Строка пользователя для FK на identity.users вставляется SQL (tests/plugins/identity.py).
"""

from dataclasses import dataclass

import procrastinate
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.plugins.database import make_uow
from tests.plugins.identity import insert_user

from app.modules.notifications.application.use_cases.grant_telegram_write_access import (
    GrantTelegramWriteAccess,
)
from app.modules.notifications.infrastructure.repositories import SqlChannelRepository
from app.modules.notifications.tests.fakes import FakeIdentity
from app.platform.contracts.events.notifications import WriteAccessGranted
from app.platform.kernel.ids import UserId, new_id
from app.platform.queue.dispatcher import EventRegistry
from app.platform.queue.port import TaskRef
from app.platform.testing.clock import FakeClock
from app.platform.testing.queue import queued_tasks

ON_WRITE_ACCESS = TaskRef("test.write_access_granted", WriteAccessGranted)
"""Подписка теста: WriteAccessGranted видно в procrastinate_jobs."""


@dataclass
class Notifications:
    session: AsyncSession
    clock: FakeClock
    identity: FakeIdentity
    grant: GrantTelegramWriteAccess

    async def user_with_chat(self) -> tuple[UserId, int]:
        """Пользователь с личным чатом (chat_id = Telegram id)."""
        user_id = await insert_user(self.session)
        chat_id = 700_000_000 + new_id().int % 100_000_000
        self.identity.chats[user_id] = chat_id
        return user_id, chat_id

    async def channels(self, user_id: UserId) -> list[dict[str, object]]:
        rows = await self.session.execute(
            text(
                "SELECT kind, address, granted_via, granted_at, disabled_at"
                " FROM notifications.channels WHERE user_id = :user_id"
            ),
            {"user_id": user_id},
        )
        return [dict(row._mapping) for row in rows]

    async def announced(self, user_id: UserId) -> list[dict[str, object]]:
        """WriteAccessGranted пользователя, поставленные в очередь (payload события)."""
        tasks = await queued_tasks(self.session, ON_WRITE_ACCESS.name)
        return [t.payload for t in tasks if t.payload.get("user_id") == str(user_id)]


@pytest.fixture
def notifications(db_session: AsyncSession, procrastinate_app: procrastinate.App) -> Notifications:
    clock = FakeClock()
    identity = FakeIdentity()
    events = EventRegistry()
    events.subscribe(WriteAccessGranted, ON_WRITE_ACCESS)
    uow = make_uow(db_session, procrastinate_app, events)
    return Notifications(
        session=db_session,
        clock=clock,
        identity=identity,
        grant=GrantTelegramWriteAccess(uow, SqlChannelRepository(db_session, uow), identity, clock),
    )
