"""Схемы HTTP messaging (ARCHITECTURE §8.5): диалоги, сообщения, начать диалог, написать."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.messaging.application.dto import ConversationView, MessagesPage
from app.modules.messaging.domain.conversation import (
    ConversationKind,
    ConversationStatus,
    ParticipantRole,
)
from app.modules.messaging.domain.message import (
    MAX_BODY,
    MAX_CLIENT_ID,
    Message,
    MessageKind,
    MessageModeration,
)
from app.platform.kernel.ids import UserId


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
            client_msg_id=message.client_msg_id if message.sender_id == viewer_id else None,
            created_at=message.created_at,
        )


class ConversationOut(BaseModel):
    """Диалог глазами участника (S29): вторая сторона, последнее сообщение, непрочитанные."""

    id: UUID
    kind: ConversationKind
    status: ConversationStatus
    my_role: ParticipantRole
    counterpart_id: UUID
    job_id: UUID | None
    response_id: UUID | None
    deal_id: UUID | None
    last_message: MessageOut | None
    unread: int
    created_at: datetime
    last_message_at: datetime | None

    @classmethod
    def of(cls, view: ConversationView, viewer_id: UserId) -> ConversationOut:
        return cls(
            id=view.id,
            kind=view.kind,
            status=view.status,
            my_role=view.my_role,
            counterpart_id=view.counterpart_id,
            job_id=view.job_id,
            response_id=view.response_id,
            deal_id=view.deal_id,
            last_message=MessageOut.of(view.last_message, viewer_id) if view.last_message else None,
            unread=view.unread,
            created_at=view.created_at,
            last_message_at=view.last_message_at,
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
        cls, conversation: ConversationView, page: MessagesPage, viewer_id: UserId
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
