"""Фасад messaging (ADR-0020 §6): модерация читает и скрывает сообщения в своей транзакции."""

from uuid import UUID

from app.modules.messaging.api import MessageForReview
from app.modules.messaging.application.ports import MessageStore
from app.modules.messaging.domain.message import MessageModeration
from app.platform.db.port import UnitOfWork
from app.platform.text.contact_masking import mask_contacts


class MessagingFacade:
    def __init__(self, uow: UnitOfWork, messages: MessageStore) -> None:
        self._uow, self._messages = uow, messages

    async def message_for_review(self, message_id: UUID) -> MessageForReview | None:
        message = await self._messages.get(message_id)
        if (
            message is None
            or message.sender_id is None
            or not message.body
            or message.moderation is MessageModeration.HIDDEN
        ):
            return None
        # контакты — правило переписки, не модерации: до договорённости они уже скрыты, после —
        # разрешены (ADR-0010); проверяется остальной текст
        return MessageForReview(sender_id=message.sender_id, text=mask_contacts(message.body))

    async def approve_message(self, message_id: UUID) -> None:
        self._uow.require_active()
        await self._messages.moderate(message_id, hidden=False)

    async def hide_message(self, message_id: UUID) -> None:
        self._uow.require_active()
        await self._messages.moderate(message_id, hidden=True)
