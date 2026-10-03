"""Что со сделкой — в ленту диалога (подписчики DealAgreed и DealCancelled; DEVELOPMENT_PLAN 6.3b):
«Договорились», «Предложение отклонено» и т. п. системным сообщением. Диалог сделки — тот, где
нажали «Договорились», или диалог по отклику, который выбрал клиент: сделка становится сделкой
диалога, и контакты в нём открываются. Повтор задачи второго сообщения не пишет.
"""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.modules.messaging.application.ports import ConversationRepository, MessageStore
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
        self, uow: UnitOfWork, conversations: ConversationRepository, messages: MessageStore
    ) -> None:
        self._uow, self._conversations, self._messages = uow, conversations, messages

    async def __call__(self, cmd: RecordDealEventCommand) -> bool:
        """Записали сообщение — True; диалога у сделки нет или сообщение уже есть — False."""
        conversation_id = await self._conversations.of_deal(cmd.deal_id)
        if conversation_id is None and cmd.response_id is not None:
            conversation_id = await self._conversations.of_response(cmd.response_id)
        if conversation_id is None:
            return False
        async with self._uow:
            conversation = await self._conversations.get_for_update(conversation_id)
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
