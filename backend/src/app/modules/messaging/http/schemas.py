"""Схемы HTTP messaging (ARCHITECTURE §8.5): диалоги, сообщения, начать диалог, написать."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.identity.api import BlockSide
from app.modules.messaging.application.cards import ConversationCard
from app.modules.messaging.application.dto import MessagesPage
from app.modules.messaging.domain.conversation import (
    ConversationKind,
    ConversationStatus,
    ParticipantRole,
)
from app.modules.messaging.domain.message import (
    MAX_BODY,
    MAX_CLIENT_ID,
    ContactType,
    Message,
    MessageKind,
    MessageModeration,
    SystemEvent,
)
from app.platform.kernel.ids import UserId


class ContactOut(BaseModel):
    """Контакт, которым сторона поделилась после договорённости (S54)."""

    type: ContactType
    value: str = Field(description="«@username» или телефон в E.164")


class SystemEventOut(BaseModel):
    """Системное сообщение: что случилось со сделкой диалога."""

    type: SystemEvent
    deal_id: UUID
    by: str | None = Field(
        description="Кто: `client`, `performer`; у отмены ещё `system` (истекло, удалён аккаунт)"
    )
    reason: str | None = Field(description="Причина отмены (DealCancelReason)")
    proposal: bool = Field(
        default=False,
        description="Отменили предложение «Договорились», а не сделку: «Предложение не принято»",
    )


class MessageOut(BaseModel):
    id: UUID
    kind: MessageKind
    mine: bool = Field(description="Моё сообщение")
    sender_id: UUID | None = Field(description="None — системное")
    body: str | None = Field(description="Скрыто модерацией или стёрто — null")
    masked: bool = Field(description="Контакты скрыты: откроются после договорённости")
    prepayment: bool = Field(description="Просьба о предоплате: под сообщением памятка")
    hidden: bool = Field(description="Скрыто модерацией")
    offer: dict[str, Any] | None = Field(
        description="Предложение отклика (kind=offer): price_type, price_amount, availability_note"
    )
    contact: ContactOut | None = Field(description="Контакт (kind=contact_share)")
    event: SystemEventOut | None = Field(description="Что со сделкой (kind=system)")
    client_msg_id: str | None = Field(description="Ключ идемпотентности — только у своих")
    created_at: datetime

    @classmethod
    def of(cls, message: Message, viewer_id: UserId) -> MessageOut:
        payload = message.payload
        offer = (
            {
                "price_type": payload.get("price_type"),
                "price_amount": payload.get("price_amount"),
                "availability_note": payload.get("availability_note"),
            }
            if message.kind is MessageKind.OFFER
            else None
        )
        return cls(
            id=message.id,
            kind=message.kind,
            mine=message.sender_id == viewer_id,
            sender_id=message.sender_id,
            body=message.body,
            masked=bool(payload.get("masked")),
            prepayment=bool(payload.get("prepayment")),
            hidden=message.moderation is MessageModeration.HIDDEN,
            offer=offer,
            contact=_contact(message),
            event=_event(message),
            client_msg_id=message.client_msg_id if message.sender_id == viewer_id else None,
            created_at=message.created_at,
        )


def _contact(message: Message) -> ContactOut | None:
    payload = message.payload
    if message.kind is not MessageKind.CONTACT_SHARE or "value" not in payload:
        return None  # стёрт: аккаунт удалён или срок хранения вышел
    return ContactOut(type=ContactType(str(payload["contact_type"])), value=str(payload["value"]))


def _event(message: Message) -> SystemEventOut | None:
    payload = message.payload
    if message.kind is not MessageKind.SYSTEM or "event" not in payload:
        return None
    by, reason = payload.get("by"), payload.get("reason")
    return SystemEventOut(
        type=SystemEvent(str(payload["event"])),
        deal_id=UUID(str(payload["deal_id"])),
        by=str(by) if by is not None else None,
        reason=str(reason) if reason is not None else None,
        proposal=payload.get("proposal") == "true",
    )


class ConversationDealOut(BaseModel):
    """Сделка диалога: шапка S30 «Сделки пока нет», «Ждёт подтверждения», «Договорились»."""

    id: UUID
    status: str = Field(description="proposed | agreed | completed | cancelled | disputed")
    title: str


class ConversationOut(BaseModel):
    """Диалог глазами участника (S29, шапка S30): вторая сторона, заявка, сделка, последнее
    сообщение, непрочитанные."""

    id: UUID
    kind: ConversationKind
    status: ConversationStatus
    my_role: ParticipantRole
    counterpart_id: UUID
    counterpart_name: str | None = Field(description="Имя второй стороны; null — аккаунт удалён")
    counterpart_profile_id: UUID | None = Field(
        description="Опубликованный профиль второй стороны-исполнителя: ссылка на S08"
    )
    counterpart_telegram: str | None = Field(
        description="«@username» второй стороны после договорённости, если она его показывает"
    )
    contacts_open: bool = Field(
        description="Контакты открыты: эта пара уже договаривалась — в этом диалоге или в другом"
        " (новое предложение, отмена и новый диалог их снова не закрывают). Телефоны в новых"
        " сообщениях не скрываются; «Поделиться контактом» — когда в диалоге есть сделка"
    )
    job_id: UUID | None
    job_title: str | None = Field(description="Заявка диалога по отклику: «Заявка: …»")
    response_id: UUID | None
    deal: ConversationDealOut | None
    last_message: MessageOut | None
    unread: int
    created_at: datetime
    last_message_at: datetime | None
    blocked: bool = Field(
        description="Блокировка между сторонами (4.7): писать, договариваться и делиться"
        " контактом нельзя, переписка — только для чтения"
    )
    blocked_by_me: bool = Field(description="Заблокировал я: в меню S30 — «Разблокировать»")

    @classmethod
    def of(cls, card: ConversationCard, viewer_id: UserId) -> ConversationOut:
        view, deal = card.view, card.deal
        return cls(
            id=view.id,
            kind=view.kind,
            status=view.status,
            my_role=view.my_role,
            counterpart_id=view.counterpart_id,
            counterpart_name=card.counterpart_name,
            counterpart_profile_id=card.counterpart_profile_id,
            counterpart_telegram=card.counterpart_telegram,
            contacts_open=card.contacts_open,
            job_id=view.job_id,
            job_title=card.job_title,
            response_id=view.response_id,
            deal=(
                ConversationDealOut(id=deal.id, status=deal.status, title=deal.title)
                if deal is not None
                else None
            ),
            last_message=MessageOut.of(view.last_message, viewer_id) if view.last_message else None,
            unread=view.unread,
            created_at=view.created_at,
            last_message_at=view.last_message_at,
            blocked=card.block is not None,
            blocked_by_me=card.block is BlockSide.BY_ME,
        )


class ConversationsPageOut(BaseModel):
    items: list[ConversationOut]
    next_cursor: str | None


class MessagesPageOut(BaseModel):
    conversation: ConversationOut
    items: list[MessageOut] = Field(description="По порядку: старые → новые")
    older_cursor: str | None = Field(description="Более ранние; null — начало диалога")
    newer_cursor: str | None = Field(description="С чего спрашивать новые (поллинг S30)")

    @classmethod
    def of(
        cls, conversation: ConversationCard, page: MessagesPage, viewer_id: UserId
    ) -> MessagesPageOut:
        return cls(
            conversation=ConversationOut.of(conversation, viewer_id),
            items=[MessageOut.of(message, viewer_id) for message in page.items],
            older_cursor=page.older,
            newer_cursor=page.newer,
        )


class ConversationStartIn(BaseModel):
    """Начать диалог: по отклику (`response_id`) или напрямую специалисту (`profile_id`)."""

    response_id: UUID | None = None
    profile_id: UUID | None = None

    @model_validator(mode="after")
    def _one_target(self) -> ConversationStartIn:
        if (self.response_id is None) == (self.profile_id is None):
            raise ValueError("нужен ровно один из response_id и profile_id")
        return self


class ConversationStartOut(BaseModel):
    id: UUID
    created: bool = Field(description="Диалог создан сейчас; false — уже был")


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_BODY)
    client_msg_id: str | None = Field(
        default=None, max_length=MAX_CLIENT_ID, description="Повтор с тем же — то же сообщение"
    )


class ReadIn(BaseModel):
    message_id: UUID = Field(description="Последнее сообщение, которое участник видел")


class DealProposalIn(BaseModel):
    """«Договорились» (S30): что делаем, цена и когда — вторая сторона увидит их на S53."""

    title: str = Field(min_length=1, max_length=120, description="Что делаем")
    price_type: Literal["fixed", "from", "hourly", "negotiable"] | None = None
    price_amount: int | None = Field(default=None, ge=1, description="Пара; без вида цены — 422")
    scheduled_at: datetime | None = Field(
        default=None, description="Когда: впереди и не дальше трёх месяцев"
    )


class DealProposalOut(BaseModel):
    deal_id: UUID = Field(description="Сделка `proposed`: ждёт подтверждения второй стороны")


class ContactShareIn(BaseModel):
    """Чем поделиться (S54): username Telegram — из initData, телефон — из `requestContact`."""

    contact_type: ContactType
    init_data: str | None = Field(
        default=None, max_length=8192, description="telegram: `Telegram.WebApp.initData`"
    )
    contact: str | None = Field(
        default=None,
        max_length=8192,
        description="phone: поле `response` из ответа `requestContact` (подписано Telegram)",
    )
