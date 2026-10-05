"""Написать в диалог (POST /conversations/{id}/messages, S30; DEVELOPMENT_PLAN 6.3a): участник
открытого диалога; пока эта пара ни разу не договорилась, контакты в тексте скрываются
(contacts.py), просьба о предоплате отмечается. Повтор с тем же `client_msg_id` — то же
сообщение, без второго. Санкция «переписка» или блокировка аккаунта — 403 `restricted`;
блокировка между сторонами (4.7) — 409 `conversation_closed` (`blocked` заблокировавшему,
нейтральный `closed` заблокированному — application/blocks.py). Лимит — по уровню
доверия (§13.3: 20 или 100 в час). Текст уходит на проверку (ModerationRequested), вторая
сторона получит уведомление (MessageSent, 6.3b)."""

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.deals.api import DealsApi
from app.modules.identity.api import Action, IdentityApi
from app.modules.messaging.application.blocks import ensure_unblocked
from app.modules.messaging.application.contacts import contacts_locked
from app.modules.messaging.application.ports import (
    ConversationRepository,
    MessageQuota,
    MessageStore,
)
from app.modules.messaging.domain.message import Message, MessageKind, check_client_id, compose
from app.modules.messaging.errors import InvalidMessageError
from app.platform.contracts.events.messaging import MessageSent
from app.platform.contracts.events.moderation import ModerationRequested
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId, new_id

TRUSTED_LEVEL: Final = 2
"""С уровня доверия 2 — повышенный лимит сообщений (§13.3)."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SendMessageCommand:
    actor_id: UserId
    trust_level: int
    conversation_id: UUID
    body: str
    client_msg_id: str | None = None


class SendMessage:
    def __init__(
        self,
        uow: UnitOfWork,
        conversations: ConversationRepository,
        messages: MessageStore,
        quota: MessageQuota,
        deals: DealsApi,
        identity: IdentityApi,
        clock: Clock,
    ) -> None:
        self._uow, self._conversations, self._messages = uow, conversations, messages
        self._quota, self._deals, self._identity, self._clock = quota, deals, identity, clock

    async def __call__(self, cmd: SendMessageCommand) -> Message:
        client_msg_id = check_client_id(cmd.client_msg_id)
        await self._identity.ensure_allowed(cmd.actor_id, Action.MESSAGE)
        async with self._uow:
            conversation = await self._conversations.get_for_update(cmd.conversation_id)
            conversation.participant(cmd.actor_id)
            if client_msg_id is not None:  # повтор ждал замка диалога — отдаём записанное
                sent = await self._messages.by_client_id(cmd.actor_id, client_msg_id)
                if sent is not None:
                    return _same_conversation(sent, conversation.id)
            sender = conversation.ensure_writable(cmd.actor_id)
            await ensure_unblocked(self._identity, conversation, cmd.actor_id)
            recipient = conversation.counterpart(cmd.actor_id)
            locked = await contacts_locked(self._deals, conversation)
            composed = compose(cmd.body, contacts_locked=locked)
            await self._quota.take_message(cmd.actor_id, trusted=cmd.trust_level >= TRUSTED_LEVEL)
            now = self._clock.now()
            draft = Message(
                id=new_id(),
                conversation_id=conversation.id,
                sender_id=cmd.actor_id,
                kind=MessageKind.TEXT,
                body=composed.body,
                payload=composed.payload,
                client_msg_id=client_msg_id,
                created_at=now,
            )
            message = await self._messages.add(draft)
            if message.id != draft.id:  # тот же ключ одновременно ушёл в другой диалог
                return _same_conversation(message, conversation.id)
            conversation.message_posted(sender_id=cmd.actor_id, message_id=message.id, now=now)
            await self._conversations.save(conversation)
            self._uow.add_event(
                MessageSent(
                    conversation_id=conversation.id,
                    message_id=message.id,
                    sender_id=cmd.actor_id,
                    recipient_id=recipient.user_id,
                    sender_role=sender.role.value,
                    masked=composed.masked,
                    occurred_at=now,
                )
            )
            self._uow.add_event(
                ModerationRequested(
                    entity_type="message",
                    entity_id=message.id,
                    author_id=cmd.actor_id,
                    occurred_at=now,
                )
            )
        return message


def _same_conversation(sent: Message, conversation_id: UUID) -> Message:
    """Ключ `client_msg_id` уже занят: в этом диалоге — то же сообщение, в другом — ошибка."""
    if sent.conversation_id != conversation_id:
        raise InvalidMessageError(field="client_msg_id", reason="reused")
    return sent
