"""Что со сделкой — в ленту диалога (подписчики DealAgreed и DealCancelled; DEVELOPMENT_PLAN 6.3b):
«Договорились», «Предложение отклонено» и т. п. системным сообщением. Диалог сделки — тот, где
нажали «Договорились», или диалог по отклику, который выбрал клиент: сделка становится сделкой
диалога, и контакты в нём открываются. Повтор задачи второго сообщения не пишет.

У сделки всегда есть чат (UX_GUIDANCE №2): клиент выбрал отклик, а диалога по нему ещё нет — он
открывается сам, как «Написать» на S24, но без лимита новых диалогов: первое сообщение — сам
отклик, клиент его уже прочитал (он его выбрал), за ним — «Договорились». S26 ведёт «Написать»
сюда одним нажатием.
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.modules.deals.api import DealsApi
from app.modules.jobs.api import ChatResponse, JobsApi
from app.modules.messaging.application.ports import ConversationRepository, MessageStore
from app.modules.messaging.application.use_cases.start_conversation import post_offer
from app.modules.messaging.domain.conversation import Conversation
from app.modules.messaging.domain.message import SystemEvent, system_message
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import new_id


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordDealEventCommand:
    deal_id: UUID
    response_id: UUID | None
    event: SystemEvent
    at: datetime
    details: dict[str, str] = field(default_factory=dict)


class RecordDealEvent:
    def __init__(
        self,
        uow: UnitOfWork,
        conversations: ConversationRepository,
        messages: MessageStore,
        jobs: JobsApi,
        deals: DealsApi,
    ) -> None:
        self._uow, self._conversations, self._messages = uow, conversations, messages
        self._jobs, self._deals = jobs, deals

    async def __call__(self, cmd: RecordDealEventCommand) -> bool:
        """Записали сообщение — True; диалога у сделки нет или сообщение уже есть — False."""
        conversation_id = await self._conversations.for_deal(cmd.deal_id, cmd.response_id)
        response = None
        if conversation_id is None and cmd.event is SystemEvent.DEAL_AGREED and cmd.response_id:
            # отклик читаем до транзакции: у jobs она своя
            response = await self._jobs.chat_response(cmd.response_id)
        if conversation_id is None and response is None:
            return False
        async with self._uow:
            if conversation_id is not None:
                conversation = await self._conversations.get_for_update(conversation_id)
            else:
                assert response is not None  # noqa: S101 — проверено выше
                conversation = await self._open(response, cmd.deal_id, cmd.at)
            key = f"{cmd.event.value}:{cmd.deal_id}"
            if await self._messages.system_exists(conversation.id, key):
                return False
            if cmd.event is SystemEvent.DEAL_AGREED:
                conversation.link_deal(cmd.deal_id)
            await self._messages.add(
                system_message(
                    message_id=new_id(),
                    conversation_id=conversation.id,
                    event=cmd.event,
                    deal_id=cmd.deal_id,
                    now=cmd.at,
                    **cmd.details,
                )
            )
            conversation.system_posted(cmd.at)
            await self._conversations.save(conversation)
        return True

    async def _open(self, response: ChatResponse, deal_id: UUID, at: datetime) -> Conversation:
        """Диалог выбранного отклика — в транзакции вызывающего, под замком пары, как «Написать»:
        успели начать его раньше — тот же."""
        await self._conversations.lock_pair(response.client_id, response.performer_id)
        if (found := await self._conversations.of_response(response.id)) is not None:
            return await self._conversations.get_for_update(found)
        conversation = Conversation.for_response(
            conversation_id=new_id(),
            client_id=response.client_id,
            performer_id=response.performer_id,
            initiator_id=response.client_id,
            job_id=response.job_id,
            response_id=response.id,
            now=at,
        )
        conversation.link_deal(deal_id)  # контакты открыты уже в первом сообщении
        await self._conversations.add(conversation)
        offer = await post_offer(self._messages, self._deals, conversation, response)
        conversation.message_posted(sender_id=response.performer_id, message_id=offer.id, now=at)
        # отклик клиент выбрал — он его прочитал: диалог не приходит к нему «непрочитанным»
        conversation.read(response.client_id, offer.id)
        return conversation
