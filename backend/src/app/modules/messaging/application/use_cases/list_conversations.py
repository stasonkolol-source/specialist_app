"""Мои диалоги (GET /conversations, S29; DEVELOPMENT_PLAN 6.3a): свежие первыми, с последним
сообщением и числом непрочитанных."""

from dataclasses import dataclass

from app.modules.messaging.application.dto import ConversationView
from app.modules.messaging.application.ports import ConversationQueries
from app.platform.kernel.ids import UserId
from app.platform.kernel.pagination import Page, PageRequest


@dataclass(frozen=True, slots=True, kw_only=True)
class ListConversationsCommand:
    actor_id: UserId
    page: PageRequest


class ListConversations:
    def __init__(self, queries: ConversationQueries) -> None:
        self._queries = queries

    async def __call__(self, cmd: ListConversationsCommand) -> Page[ConversationView]:
        return await self._queries.mine(cmd.actor_id, page=cmd.page)
