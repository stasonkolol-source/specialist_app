"""«Договорились» в чате (POST /conversations/{id}/deal, S30; DEVELOPMENT_PLAN 6.3b): сторона
прямого диалога предлагает условия — что, цена, когда. Сделка `proposed` (deals) и системное
сообщение в ленте — в одной транзакции; вторая сторона подтверждает или отклоняет за 72 ч (S53).

В диалоге по отклику договорённость — выбор отклика клиентом (S24, `POST /responses/{id}/accept`):
там 409 `cannot_propose`. Предложение ждёт ответа или сделка идёт — 409 `deal_in_progress`; после
завершения или отмены можно договориться снова.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from app.modules.deals.api import DealsApi, InvalidDealError, ProposedDealIn
from app.modules.identity.api import Action, IdentityApi
from app.modules.messaging.application.blocks import ensure_unblocked
from app.modules.messaging.application.contacts import ACTIVE_DEALS, current_deal
from app.modules.messaging.application.ports import ConversationRepository, MessageStore
from app.modules.messaging.domain.conversation import ConversationKind
from app.modules.messaging.domain.message import SystemEvent, system_message
from app.modules.messaging.errors import CannotProposeError, DealInProgressError
from app.modules.specialists.api import SpecialistsApi
from app.platform.db.port import UnitOfWork
from app.platform.kernel.clock import Clock
from app.platform.kernel.ids import DealId, UserId, new_id

HORIZON: Final = timedelta(days=90)
"""Договориться можно на время не дальше трёх месяцев вперёд."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ProposeDealCommand:
    actor_id: UserId
    conversation_id: UUID
    title: str
    price_type: str | None = None
    price_amount: int | None = None
    scheduled_at: datetime | None = None


class ProposeDeal:
    def __init__(
        self,
        uow: UnitOfWork,
        conversations: ConversationRepository,
        messages: MessageStore,
        deals: DealsApi,
        specialists: SpecialistsApi,
        identity: IdentityApi,
        clock: Clock,
    ) -> None:
        self._uow, self._conversations, self._messages = uow, conversations, messages
        self._deals, self._specialists = deals, specialists
        self._identity, self._clock = identity, clock

    async def __call__(self, cmd: ProposeDealCommand) -> DealId:
        await self._identity.ensure_allowed(cmd.actor_id, Action.MESSAGE)
        now = self._clock.now()
        _check_terms(cmd, now)
        async with self._uow:
            conversation = await self._conversations.get_for_update(cmd.conversation_id)
            proposer = conversation.ensure_writable(cmd.actor_id)
            await ensure_unblocked(self._identity, conversation, cmd.actor_id)
            if conversation.kind is not ConversationKind.DIRECT:
                raise CannotProposeError(reason="choose_response")
            deal = await current_deal(self._deals, conversation)
            if deal is not None and deal.status in ACTIVE_DEALS:
                raise DealInProgressError(deal_id=str(deal.id))
            performer_id = conversation.performer.user_id
            profile = await self._specialists.profile_of(performer_id)
            deal_id = await self._deals.propose(
                ProposedDealIn(
                    client_id=conversation.client.user_id,
                    performer_id=performer_id,
                    proposed_by=cmd.actor_id,
                    profile_id=profile.id if profile is not None else None,
                    conversation_id=conversation.id,
                    title=cmd.title,
                    price_type=cmd.price_type,
                    agreed_price=cmd.price_amount,
                    scheduled_at=cmd.scheduled_at,
                )
            )
            conversation.link_deal(deal_id)
            await self._messages.add(
                system_message(
                    message_id=new_id(),
                    conversation_id=conversation.id,
                    event=SystemEvent.DEAL_PROPOSED,
                    deal_id=deal_id,
                    now=now,
                    by=proposer.role.value,
                )
            )
            conversation.system_posted(now)
            await self._conversations.save(conversation)
        return deal_id


def _check_terms(cmd: ProposeDealCommand, now: datetime) -> None:
    """Цена — с видом цены; время — впереди и не дальше трёх месяцев."""
    if cmd.price_amount is not None and cmd.price_type is None:
        raise InvalidDealError(field="price_type", reason="required")
    if cmd.scheduled_at is not None:
        if cmd.scheduled_at.tzinfo is None:
            raise InvalidDealError(field="scheduled_at", reason="no_timezone")
        if cmd.scheduled_at < now:
            raise InvalidDealError(field="scheduled_at", reason="past")
        if cmd.scheduled_at > now + HORIZON:
            raise InvalidDealError(field="scheduled_at", reason="too_far")
