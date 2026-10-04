"""Адаптер цели «сообщение» (план 6.3a): чистый итог автопроверки не возвращает сообщение,
которое модератор скрыл, пока она шла; одобрение модератора — возвращает."""

from typing import cast
from uuid import UUID

import pytest

from app.modules.messaging.api import MessagingApi
from app.modules.moderation.infrastructure.targets.message import MessageTarget
from app.platform.kernel.ids import new_id

pytestmark = pytest.mark.unit


class Messaging:
    def __init__(self) -> None:
        self.calls: list[tuple[str, UUID]] = []

    async def approve_message(self, message_id: UUID) -> None:
        self.calls.append(("approve", message_id))

    async def hide_message(self, message_id: UUID) -> None:
        self.calls.append(("hide", message_id))


async def test_late_auto_check_leaves_a_hidden_message_hidden() -> None:
    messaging = Messaging()
    target = MessageTarget(cast(MessagingApi, messaging))
    message_id = new_id()

    await target.hide(message_id, reason_code="contact_leak")  # модератор по жалобе
    await target.publish(message_id, auto=True)  # опоздавший чистый итог автопроверки
    await target.publish(message_id)  # модератор снял скрытие

    assert messaging.calls == [("hide", message_id), ("approve", message_id)]
