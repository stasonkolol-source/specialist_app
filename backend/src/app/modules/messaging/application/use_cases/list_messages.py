"""Сообщения диалога (GET /conversations/{id}/messages, S30; DEVELOPMENT_PLAN 6.3a): старые →
новые; более ранние — `direction=older` от курсора, новые для поллинга — `direction=newer`.
Чужой диалог — 404."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.messaging.application.dto import ConversationView, MessagesPage
from app.modules.messaging.application.ports import ConversationQueries, Direction
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
    conversation: ConversationView
    page: MessagesPage


class ListMessages:
    def __init__(self, queries: ConversationQueries) -> None:
        self._queries = queries

    async def __call__(self, cmd: ListMessagesCommand) -> ConversationMessages:
        conversation = await self._queries.view(cmd.conversation_id, cmd.actor_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id=cmd.conversation_id)
        page = await self._queries.messages(
            cmd.conversation_id,
            viewer_id=cmd.actor_id,
            cursor=cmd.cursor,
            direction=cmd.direction,
            limit=cmd.limit,
        )
        return ConversationMessages(conversation=conversation, page=page)
