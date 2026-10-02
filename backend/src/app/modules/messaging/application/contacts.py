"""Открыты ли контакты в диалоге (ADR-0010, ARCHITECTURE §11.5): только когда стороны
договорились — сделка `agreed` или уже `completed`. До этого телефоны, ссылки и @username в
сообщениях скрываются."""

from typing import Final

from app.modules.deals.api import DealsApi
from app.modules.messaging.domain.conversation import Conversation
from app.platform.kernel.ids import DealId

OPEN_DEALS: Final = frozenset({"agreed", "completed"})


async def contacts_locked(deals: DealsApi, conversation: Conversation) -> bool:
    if conversation.deal_id is not None:
        deal = await deals.deal_brief(DealId(conversation.deal_id))
    elif conversation.response_id is not None:
        deal = await deals.deal_for_response(conversation.response_id)
    else:
        deal = None
    return deal is None or deal.status not in OPEN_DEALS
