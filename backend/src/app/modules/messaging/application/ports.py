"""Порты messaging (ADR-0020 §1): диалоги, сообщения, чтение для экранов, лимиты, задачи."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, Protocol
from uuid import UUID

from app.modules.messaging.application.dto import ConversationView, MessagesPage, ResponseStat
from app.modules.messaging.domain.conversation import Conversation, ParticipantRole
from app.modules.messaging.domain.message import ContactType, Message
from app.platform.contracts.events.deals import DealAgreed, DealCancelled
from app.platform.contracts.events.identity import UserDeleted
from app.platform.kernel.ids import MediaId, UserId
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

    async def of_deal(self, deal_id: UUID) -> UUID | None:
        """Диалог, где договорились (`deal_id`)."""
        ...


class MessageStore(Protocol):
    async def add(self, message: Message) -> Message:
        """Записать сообщение; повтор `client_msg_id` того же автора — уже записанное."""
        ...

    async def by_client_id(self, sender_id: UserId, client_msg_id: str) -> Message | None:
        """Сообщение, уже отправленное с этим ключом идемпотентности."""
        ...

    async def system_exists(self, conversation_id: UUID, key: str) -> bool:
        """Системное сообщение с этим ключом (`<событие>:<сделка>`) в диалоге уже есть."""
        ...

    async def get(self, message_id: UUID) -> Message | None: ...

    async def recent(
        self, conversation_id: UUID, sender_id: UserId, *, since: datetime, limit: int
    ) -> list[Message]:
        """Последние текстовые сообщения отправителя в диалоге с `since` — по порядку
        отправки: окно номера по частям (QA ADV-06)."""
        ...

    async def mask(self, message: Message, body: str) -> None:
        """Текст с задним числом скрытой частью контакта и отметка `masked` (QA ADV-06)."""
        ...

    async def moderate(self, message_id: UUID, *, hidden: bool) -> bool:
        """Решение модерации: скрыть или вернуть «ок»; сообщения нет — False."""
        ...

    async def forget(self, user_id: UserId, *, now: datetime) -> int:
        """Аккаунт удалён: текст его сообщений стирается (§7.10)."""
        ...


class ConversationRetention(Protocol):
    """Срок хранения переписки (2.12b, §7.10): кандидаты и физическое удаление диалога."""

    async def inactive(self, before: datetime, *, after: UUID | None, limit: int) -> list[UUID]:
        """Диалоги без сообщений с `before` (у пустого — с создания), по id."""
        ...

    async def deals(self, conversation_ids: Collection[UUID]) -> dict[UUID, UUID]:
        """Сделки диалогов (диалог → сделка): спор держит переписку."""
        ...

    async def messages(self, conversation_ids: Collection[UUID]) -> dict[UUID, UUID]:
        """Сообщения диалогов (сообщение → диалог): кейс о сообщении держит переписку."""
        ...

    async def attachments(self, conversation_ids: Collection[UUID]) -> list[tuple[UserId, MediaId]]:
        """Файлы сообщений с отправителем: удалить вместе с диалогом."""
        ...

    async def purge(self, conversation_ids: Collection[UUID]) -> None:
        """Удалить диалоги с участниками, сообщениями и записями об обмене контактами."""
        ...


class ContactShares(Protocol):
    async def message_of(
        self, deal_id: UUID, shared_by: UserId, contact_type: ContactType
    ) -> UUID | None:
        """Сообщение, которым сторона уже поделилась этим контактом по сделке."""
        ...

    async def add(
        self,
        *,
        conversation_id: UUID,
        deal_id: UUID,
        shared_by: UserId,
        shared_with: UserId,
        contact_type: ContactType,
        message_id: UUID,
    ) -> None: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifiedContact:
    """Контакт из подписи Telegram и чей он."""

    telegram_id: int
    value: str | None
    """«@username» или телефон в E.164; None — username в Telegram нет."""


class ContactVerifier(Protocol):
    """Подпись Telegram (ADR-0009): контакт берём только из подписанных ботом данных.
    InvalidContactError — подпись не сошлась (`signature`) или устарела (`expired`)."""

    def telegram(self, init_data: str) -> VerifiedContact:
        """username из initData Mini App: подпись не старше суток."""
        ...

    def phone(self, contact: str) -> VerifiedContact:
        """Телефон из ответа `requestContact`: подпись не старше часа."""
        ...


class ConversationQueries(Protocol):
    """Чтение для экранов: без блокировок и UoW."""

    async def mine(
        self, user_id: UserId, *, role: ParticipantRole | None, page: PageRequest
    ) -> Page[ConversationView]:
        """Диалоги участника: свежие первыми (по последнему сообщению); `role` — только те, где
        он клиент или исполнитель (вкладки S29)."""
        ...

    async def unread_total(self, user_id: UserId) -> int:
        """Непрочитанные сообщения во всех диалогах — бейдж «Сообщения N» таббара (6.4)."""
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

    async def response_stats(
        self, *, since: datetime, min_conversations: int
    ) -> list[ResponseStat]:
        """Медиана первого ответа исполнителей по диалогам, где клиент впервые написал после
        `since`; исполнители, у кого диалогов с ответом меньше `min_conversations`, — без неё."""
        ...


class Presence(Protocol):
    """Кто сейчас смотрит диалог (S30 опрашивает новые каждые 3–5 с): уведомление о сообщении
    такому получателю не нужно (§11.3). Метка короткая и без гарантий: нет Valkey — «не смотрит»,
    уведомление уйдёт."""

    async def viewing(self, conversation_id: UUID, user_id: UserId) -> None: ...

    async def is_viewing(self, conversation_id: UUID, user_id: UserId) -> bool: ...


class MessageQuota(Protocol):
    async def take_message(self, user_id: UserId, *, trusted: bool) -> None:
        """Сообщение за час (§13.3): 20 у уровней 0–1, 100 у проверенных; сверх — 429."""
        ...

    async def take_conversation(self, user_id: UserId) -> None:
        """Новый диалог за час (§13.3): не больше пяти; сверх — 429."""
        ...


FORGET_MESSAGES: Final = TaskRef("messaging.forget_messages", UserDeleted)
"""Аккаунт удалён — текст его сообщений стирается (§7.10)."""
RECORD_DEAL_AGREED: Final = TaskRef("messaging.record_deal_agreed", DealAgreed)
"""Договорились (подтверждено «Договорились» или выбран отклик) — системное сообщение в диалоге
и сделка диалога: контакты открыты (6.3b)."""
RECORD_DEAL_CANCELLED: Final = TaskRef("messaging.record_deal_cancelled", DealCancelled)
"""Предложение отклонено, истекло или сделку отменили — системное сообщение в диалоге (6.3b)."""
