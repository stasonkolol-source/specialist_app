"""«Поделиться контактом» (POST /conversations/{id}/share-contact, S54; DEVELOPMENT_PLAN 6.3b;
ADR-0010): после договорённости каждая сторона явным действием отдаёт свой контакт — username
Telegram или телефон. Это и есть double opt-in: до сделки `agreed` — 409 `contacts_locked`.

Контакт берём только из подписанного Telegram: username — из initData Mini App, телефон — из
ответа `requestContact`. Оба должны принадлежать тому, кто делится (Telegram id совпадает).
Контакт уходит второй стороне сообщением в диалоге; повтор того же контакта по той же сделке —
то же сообщение.
"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.deals.api import DealsApi
from app.modules.identity.api import Action, IdentityApi
from app.modules.messaging.application.contacts import OPEN_DEALS, current_deal
from app.modules.messaging.application.ports import (
    ContactShares,
    ContactVerifier,
    ConversationRepository,
    MessageStore,
)
from app.modules.messaging.domain.message import ContactType, Message, MessageKind
from app.modules.messaging.errors import ContactsLockedError, InvalidContactError
from app.platform.contracts.events.messaging import ContactShared
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId, new_id


@dataclass(frozen=True, slots=True, kw_only=True)
class ShareContactCommand:
    actor_id: UserId
    conversation_id: UUID
    contact_type: ContactType
    init_data: str | None = None
    """Для `telegram`: initData Mini App — из неё username."""
    contact: str | None = None
    """Для `phone`: ответ `requestContact` (поле `response`), подписанный Telegram."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SharedContactMessage:
    message: Message
    created: bool


class ShareContact:
    def __init__(
        self,
        uow: UnitOfWork,
        conversations: ConversationRepository,
        messages: MessageStore,
        shares: ContactShares,
        deals: DealsApi,
        identity: IdentityApi,
        verifier: ContactVerifier,
        clock: Clock,
    ) -> None:
        self._uow, self._conversations, self._messages = uow, conversations, messages
        self._shares, self._deals, self._identity = shares, deals, identity
        self._verifier, self._clock = verifier, clock

    async def __call__(self, cmd: ShareContactCommand) -> SharedContactMessage:
        await self._identity.ensure_allowed(cmd.actor_id, Action.MESSAGE)
        value = await self._verified(cmd)
        async with self._uow:
            conversation = await self._conversations.get_for_update(cmd.conversation_id)
            sharer = conversation.ensure_writable(cmd.actor_id)
            other = conversation.counterpart(cmd.actor_id)
            deal = await current_deal(self._deals, conversation)
            if deal is None or deal.status not in OPEN_DEALS:
                raise ContactsLockedError(conversation_id=conversation.id)
            shared = await self._shares.message_of(deal.id, cmd.actor_id, cmd.contact_type)
            if shared is not None:
                message = await self._messages.get(shared)
                if message is not None:
                    return SharedContactMessage(message=message, created=False)
            now = self._clock.now()
            message = await self._messages.add(
                Message(
                    id=new_id(),
                    conversation_id=conversation.id,
                    sender_id=cmd.actor_id,
                    kind=MessageKind.CONTACT_SHARE,
                    body=None,
                    payload={"contact_type": cmd.contact_type.value, "value": value},
                    created_at=now,
                )
            )
            await self._shares.add(
                conversation_id=conversation.id,
                deal_id=deal.id,
                shared_by=cmd.actor_id,
                shared_with=other.user_id,
                contact_type=cmd.contact_type,
                message_id=message.id,
            )
            if conversation.deal_id is None:
                conversation.link_deal(deal.id)
            conversation.message_posted(sender_id=cmd.actor_id, message_id=message.id, now=now)
            await self._conversations.save(conversation)
            self._uow.add_event(
                ContactShared(
                    conversation_id=conversation.id,
                    deal_id=deal.id,
                    shared_by=cmd.actor_id,
                    shared_with=other.user_id,
                    sharer_role=sharer.role.value,
                    contact_type=cmd.contact_type.value,
                    occurred_at=now,
                )
            )
        return SharedContactMessage(message=message, created=True)

    async def _verified(self, cmd: ShareContactCommand) -> str:
        """Контакт из подписи Telegram; чей он — сверяем с Telegram id того, кто делится."""
        if cmd.contact_type is ContactType.TELEGRAM:
            if not cmd.init_data:
                raise InvalidContactError(reason="missing")
            verified = self._verifier.telegram(cmd.init_data)
        else:
            if not cmd.contact:
                raise InvalidContactError(reason="missing")
            verified = self._verifier.phone(cmd.contact)
        telegram_id = await self._identity.telegram_chat_id(cmd.actor_id)
        if telegram_id is None or verified.telegram_id != telegram_id:
            raise InvalidContactError(reason="not_yours")
        if verified.value is None:
            raise InvalidContactError(reason="no_username")
        return verified.value
