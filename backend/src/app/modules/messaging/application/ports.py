"""Порты messaging (ADR-0020 §1): диалоги, сообщения, чтение для экранов, лимиты, задачи."""

from datetime import datetime
from typing import Final, Literal, Protocol
from uuid import UUID

from app.modules.messaging.application.dto import ConversationView, MessagesPage
from app.modules.messaging.domain.conversation import Conversation
from app.modules.messaging.domain.message import Message
from app.platform.contracts.events.identity import UserDeleted
from app.platform.kernel.ids import UserId
from app.platform.kernel.pagination import Page, PageRequest
from app.platform.queue.port import TaskRef

Direction = Literal["older", "newer"]


class ConversationRepository(Protocol):
    async def add(self, conversation: Conversation) -> None: ...

    async def get_for_update(self, conversation_id: UUID) -> Conversation:
        """Диалог под блокировкой строки; нет — ConversationNotFoundError."""
        ...

    async def save(self, conversation: Conversation) -> None: ...

    async def lock_pair(self, client_id: UserId, performer_id: UserId) -> None:
        """Advisory lock пары: два «Написать» одновременно не создадут два диалога."""
        ...

    async def of_response(self, response_id: UUID) -> UUID | None:
        """Диалог по отклику — один на отклик."""
        ...

    async def direct_of(self, client_id: UserId, performer_id: UserId) -> UUID | None:
        """Прямой диалог клиента со специалистом — один на пару."""
        ...


class MessageStore(Protocol):
    async def add(self, message: Message) -> Message:
        """Записать сообщение; повтор `client_msg_id` того же автора — уже записанное."""
        ...

    async def by_client_id(self, sender_id: UserId, client_msg_id: str) -> Message | None:
        """Сообщение, уже отправленное с этим ключом идемпотентности."""
        ...

    async def get(self, message_id: UUID) -> Message | None: ...

    async def moderate(self, message_id: UUID, *, hidden: bool) -> bool:
        """Решение модерации: скрыть или вернуть «ок»; сообщения нет — False."""
        ...

    async def forget(self, user_id: UserId, *, now: datetime) -> int:
        """Аккаунт удалён: текст его сообщений стирается (§7.10)."""
        ...

    async def purge(self, before: datetime, *, now: datetime, limit: int) -> int:
        """Правило хранения: текст сообщений старше срока стирается порциями."""
        ...


class ConversationQueries(Protocol):
    """Чтение для экранов: без блокировок и UoW."""

    async def mine(self, user_id: UserId, *, page: PageRequest) -> Page[ConversationView]:
        """Диалоги участника: свежие первыми (по последнему сообщению)."""
        ...

    async def view(self, conversation_id: UUID, user_id: UserId) -> ConversationView | None:
        """Диалог глазами участника; чужой или нет такого — None."""
        ...

    async def messages(
        self,
        conversation_id: UUID,
        *,
        viewer_id: UserId,
        cursor: str | None,
        direction: Direction,
        limit: int,
    ) -> MessagesPage:
        """Сообщения по порядку; скрытые модерацией — без текста, кроме своих."""
        ...


class MessageQuota(Protocol):
    async def take_message(self, user_id: UserId, *, trusted: bool) -> None:
        """Сообщение за час (§13.3): 20 у уровней 0–1, 100 у проверенных; сверх — 429."""
        ...

    async def take_conversation(self, user_id: UserId) -> None:
        """Новый диалог за час (§13.3): не больше пяти; сверх — 429."""
        ...


FORGET_MESSAGES: Final = TaskRef("messaging.forget_messages", UserDeleted)
"""Аккаунт удалён — текст его сообщений стирается (§7.10)."""
