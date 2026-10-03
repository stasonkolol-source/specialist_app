"""Начать диалог (POST /conversations, S15/S23/S24 «Написать», S08; DEVELOPMENT_PLAN 6.3a):
по отклику — клиент заявки или исполнитель отклика, первое сообщение — сам отклик; напрямую —
клиент специалисту из его карточки. Диалог уже есть — тот же (повтор и гонка двух «Написать» под
замком пары не создадут второй). Новый диалог тратит часовой лимит (§13.3: пять); санкция
«переписка» или блокировка аккаунта — 403 `restricted`."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.deals.api import DealsApi
from app.modules.identity.api import Action, IdentityApi
from app.modules.jobs.api import ChatResponse, JobsApi
from app.modules.messaging.application.contacts import contacts_locked
from app.modules.messaging.application.ports import (
    ConversationRepository,
    MessageQuota,
    MessageStore,
)
from app.modules.messaging.domain.conversation import Conversation
from app.modules.messaging.domain.message import Message, MessageKind, compose
from app.modules.messaging.errors import (
    CannotStartConversationError,
    ConversationNotFoundError,
)
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import UserId, new_id

WITHDRAWN = "withdrawn"


@dataclass(frozen=True, slots=True, kw_only=True)
class StartConversationCommand:
    actor_id: UserId
    response_id: UUID | None = None
    profile_id: UUID | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class StartedConversation:
    conversation_id: UUID
    created: bool


class StartConversation:
    def __init__(
        self,
        uow: UnitOfWork,
        conversations: ConversationRepository,
        messages: MessageStore,
        quota: MessageQuota,
        jobs: JobsApi,
        deals: DealsApi,
        specialists: SpecialistsApi,
        identity: IdentityApi,
        clock: Clock,
    ) -> None:
        self._uow, self._conversations, self._messages = uow, conversations, messages
        self._quota, self._jobs, self._deals = quota, jobs, deals
        self._specialists, self._identity, self._clock = specialists, identity, clock

    async def __call__(self, cmd: StartConversationCommand) -> StartedConversation:
        if (cmd.response_id is None) == (cmd.profile_id is None):
            raise CannotStartConversationError(reason="target")
        await self._identity.ensure_allowed(cmd.actor_id, Action.MESSAGE)
        if cmd.response_id is not None:
            return await self._for_response(cmd.actor_id, cmd.response_id)
        assert cmd.profile_id is not None  # noqa: S101 — проверено выше
        return await self._direct(cmd.actor_id, cmd.profile_id)

    async def _for_response(self, actor_id: UserId, response_id: UUID) -> StartedConversation:
        response = await self._jobs.chat_response(response_id)
        if response is None or actor_id not in (response.client_id, response.performer_id):
            raise ConversationNotFoundError(response_id=response_id)
        if not response.visible_to_client or response.status == WITHDRAWN:
            raise CannotStartConversationError(reason="response_unavailable")
        found = await self._conversations.of_response(response_id)
        if found is not None:
            return StartedConversation(conversation_id=found, created=False)
        async with self._uow:
            await self._conversations.lock_pair(response.client_id, response.performer_id)
            found = await self._conversations.of_response(response_id)
            if found is not None:  # гонка: второй «Написать» ждал замка
                return StartedConversation(conversation_id=found, created=False)
            await self._quota.take_conversation(actor_id)
            now = self._clock.now()
            conversation = Conversation.for_response(
                conversation_id=new_id(),
                client_id=response.client_id,
                performer_id=response.performer_id,
                initiator_id=actor_id,
                job_id=response.job_id,
                response_id=response_id,
                now=now,
            )
            await self._conversations.add(conversation)
            offer = await self._offer(conversation, response)
            conversation.message_posted(
                sender_id=response.performer_id, message_id=offer.id, now=now
            )
            await self._conversations.save(conversation)
        return StartedConversation(conversation_id=conversation.id, created=True)

    async def _offer(self, conversation: Conversation, response: ChatResponse) -> Message:
        """Первое сообщение — сам отклик: текст (контакты скрыты, пока нет сделки) и цена."""
        locked = await contacts_locked(self._deals, conversation)
        composed = compose(response.message, contacts_locked=locked)
        payload: dict[str, object] = {
            **composed.payload,
            "price_type": response.price_type,
            "price_amount": response.price_amount,
            "availability_note": response.availability_note,
        }
        return await self._messages.add(
            Message(
                id=new_id(),
                conversation_id=conversation.id,
                sender_id=response.performer_id,
                kind=MessageKind.OFFER,
                body=composed.body,
                payload=payload,
                created_at=response.created_at,
            )
        )

    async def _direct(self, actor_id: UserId, profile_id: UUID) -> StartedConversation:
        profile = await self._specialists.public_profile(profile_id)
        if profile is None or await self._identity.hidden_from_search([profile.user_id]):
            raise CannotStartConversationError(reason="profile_unavailable")
        performer_id = profile.user_id
        if performer_id == actor_id:
            raise CannotStartConversationError(reason="self")
        found = await self._conversations.direct_of(actor_id, performer_id)
        if found is not None:
            return StartedConversation(conversation_id=found, created=False)
        async with self._uow:
            await self._conversations.lock_pair(actor_id, performer_id)
            found = await self._conversations.direct_of(actor_id, performer_id)
            if found is not None:
                return StartedConversation(conversation_id=found, created=False)
            await self._quota.take_conversation(actor_id)
            conversation = Conversation.direct(
                conversation_id=new_id(),
                client_id=actor_id,
                performer_id=performer_id,
                now=self._clock.now(),
            )
            await self._conversations.add(conversation)
        return StartedConversation(conversation_id=conversation.id, created=True)
