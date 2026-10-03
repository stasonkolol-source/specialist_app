"""Сообщения диалога (GET /conversations/{id}/messages, S30; DEVELOPMENT_PLAN 6.3a): старые →
новые; более ранние — `direction=older` от курсора, новые для поллинга — `direction=newer`.
Чужой диалог — 404. Каждый запрос отмечает, что участник смотрит диалог: уведомление о новом
сообщении ему не нужно (6.3b)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.messaging.application.cards import ConversationCard, ConversationCards
from app.modules.messaging.application.dto import MessagesPage
from app.modules.messaging.application.ports import ConversationQueries, Direction, Presence
from app.modules.messaging.errors import ConversationNotFoundError
from app.platform.kernel.ids import UserId


@dataclass(frozen=True, slots=True, kw_only=True)
class ListMessagesCommand:
    actor_id: UserId
    conversation_id: UUID
    cursor: str | None
    direction: Direction
    limit: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ConversationMessages:
    conversation: ConversationCard
    page: MessagesPage


class ListMessages:
    def __init__(
        self, queries: ConversationQueries, presence: Presence, cards: ConversationCards
    ) -> None:
        self._queries, self._presence, self._cards = queries, presence, cards

    async def __call__(self, cmd: ListMessagesCommand) -> ConversationMessages:
        conversation = await self._queries.view(cmd.conversation_id, cmd.actor_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id=cmd.conversation_id)
        await self._presence.viewing(cmd.conversation_id, cmd.actor_id)
        page = await self._queries.messages(
            cmd.conversation_id,
            viewer_id=cmd.actor_id,
            cursor=cmd.cursor,
            direction=cmd.direction,
            limit=cmd.limit,
        )
        [card] = await self._cards.of([conversation])
        return ConversationMessages(conversation=card, page=page)
