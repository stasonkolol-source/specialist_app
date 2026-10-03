"""Сделка диалога и открыты ли контакты (ADR-0010, ARCHITECTURE §11.5).

Сделка диалога — «Договорились» в нём (6.3b) или выбор отклика, по которому он начат. Контакты
открыты, только когда стороны договорились — сделка `agreed`, под спором (`disputed`: спор
открывают только по договорённости, и сторонам нужно договориться, 6.1c) или уже `completed`. До
этого телефоны, ссылки и @username в сообщениях скрываются, а «Поделиться контактом» — 409.
"""

from typing import Final

from app.modules.deals.api import DealBrief, DealsApi
from app.modules.messaging.domain.conversation import Conversation
from app.platform.kernel.ids import DealId

OPEN_DEALS: Final = frozenset({"agreed", "disputed", "completed"})
"""Договорились: контакты открыты."""
ACTIVE_DEALS: Final = frozenset({"proposed", "agreed", "disputed"})
"""Договорённость идёт (и под спором): второе «Договорились» в том же диалоге — 409."""


async def current_deal(deals: DealsApi, conversation: Conversation) -> DealBrief | None:
    if conversation.deal_id is not None:
        return await deals.deal_brief(DealId(conversation.deal_id))
    if conversation.response_id is not None:
        return await deals.deal_for_response(conversation.response_id)
    return None


async def contacts_locked(deals: DealsApi, conversation: Conversation) -> bool:
    deal = await current_deal(deals, conversation)
    return deal is None or deal.status not in OPEN_DEALS
