"""Прочитал (POST /conversations/{id}/read, S30; DEVELOPMENT_PLAN 6.3a): участник дочитал до
сообщения — непрочитанные на S29 гаснут. Более раннее, чем уже прочитанное, — ничего; сообщение
не из этого диалога — 422."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.messaging.application.ports import ConversationRepository, MessageStore
from app.modules.messaging.errors import InvalidMessageError
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ReadConversationCommand:
    actor_id: UserId
    conversation_id: UUID
    message_id: UUID


class ReadConversation:
    def __init__(
        self, uow: UnitOfWork, conversations: ConversationRepository, messages: MessageStore
    ) -> None:
        self._uow, self._conversations, self._messages = uow, conversations, messages

    async def __call__(self, cmd: ReadConversationCommand) -> None:
        async with self._uow:
            conversation = await self._conversations.get_for_update(cmd.conversation_id)
            conversation.participant(cmd.actor_id)
            message = await self._messages.get(cmd.message_id)
            if message is None or message.conversation_id != conversation.id:
                raise InvalidMessageError(field="message_id", reason="not_in_conversation")
            if conversation.read(cmd.actor_id, cmd.message_id):
                await self._conversations.save(conversation)
