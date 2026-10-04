"""Сделка диалога и открыты ли контакты (ADR-0010, ARCHITECTURE §11.5).

Сделка диалога — «Договорились» в нём (6.3b) или выбор отклика, по которому он начат. Контакты
открыты, когда стороны договорились — сделка `agreed`, под спором (`disputed`: спор открывают
только по договорённости, и сторонам нужно договориться, 6.1c) или уже `completed`. До этого
телефоны, ссылки и @username в сообщениях скрываются, а «Поделиться контактом» — 409.

Договорились однажды — контакты в этом диалоге открыты и дальше (решение владельца 2026-10-04):
новое предложение «Договориться снова» ждёт ответа, его отклонили или прошлую сделку отменили —
стороны друг друга уже знают, прятать номера снова незачем. В счёт — только сделка, дошедшая до
`agreed`: предложение, которое отклонили или которое истекло, контактов не открывало.
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


async def contacts_open(
    deals: DealsApi, conversation: Conversation, deal: DealBrief | None
) -> bool:
    """Открыты ли контакты при сделке диалога `deal` (её даёт `current_deal`). Сделки нет —
    договариваться ещё не о чем: каждое «Договорились» становится сделкой диалога, а сделка по
    отклику одна, — базу не спрашиваем."""
    if deal is None:
        return False
    if deal.status in OPEN_DEALS:
        return True
    return await deals.ever_agreed(conversation.id, conversation.response_id)


async def contacts_locked(deals: DealsApi, conversation: Conversation) -> bool:
    deal = await current_deal(deals, conversation)
    return not await contacts_open(deals, conversation, deal)
