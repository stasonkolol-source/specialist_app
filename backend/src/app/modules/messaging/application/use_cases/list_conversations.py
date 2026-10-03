"""Мои диалоги (GET /conversations, S29; DEVELOPMENT_PLAN 6.3a, 6.4): свежие первыми, с последним
сообщением и числом непрочитанных; вторая сторона, заявка и сделка — карточкой. Вкладки «Я
клиент» и «Я исполнитель» — фильтр `role`."""

from dataclasses import dataclass

from app.modules.messaging.application.cards import ConversationCard, ConversationCards
from app.modules.messaging.application.ports import ConversationQueries
from app.modules.messaging.domain.conversation import ParticipantRole
from app.platform.kernel.ids import UserId
from app.platform.kernel.pagination import Page, PageRequest


@dataclass(frozen=True, slots=True, kw_only=True)
class ListConversationsCommand:
    actor_id: UserId
    page: PageRequest
    role: ParticipantRole | None = None


class ListConversations:
    def __init__(self, queries: ConversationQueries, cards: ConversationCards) -> None:
        self._queries, self._cards = queries, cards

    async def __call__(self, cmd: ListConversationsCommand) -> Page[ConversationCard]:
        page = await self._queries.mine(cmd.actor_id, role=cmd.role, page=cmd.page)
        return Page(items=tuple(await self._cards.of(page.items)), next_cursor=page.next_cursor)
