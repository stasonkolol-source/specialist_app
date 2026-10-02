"""ORM-модели messaging (ARCHITECTURE §7.3, миграции messaging_0001–0002): диалоги, участники,
сообщения, обмен контактами. FK на identity.users, jobs.jobs, jobs.responses и deals.deals
объявлены только в миграции: MetaData модуля не знает чужих таблиц (modules/README.md).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.modules.messaging.domain.conversation import (
    ConversationKind,
    ConversationStatus,
    ParticipantRole,
)
from app.modules.messaging.domain.message import (
    MAX_BODY,
    ContactType,
    MessageKind,
    MessageModeration,
)
from app.platform.db.base import ModelBase, UuidPkMixin, module_metadata
from app.platform.db.types import str_enum

SCHEMA = "messaging"
metadata = module_metadata(SCHEMA)


class Base(ModelBase):
    __abstract__ = True
    metadata = metadata


class ConversationRow(UuidPkMixin, Base):
    __tablename__ = "conversations"

    kind: Mapped[ConversationKind] = mapped_column(str_enum(ConversationKind, "kind"))
    status: Mapped[ConversationStatus] = mapped_column(
        str_enum(ConversationStatus, "status"), server_default=ConversationStatus.OPEN.value
    )
    client_id: Mapped[UUID]
    """identity.users: FK в миграции; пара (клиент, исполнитель) — прямой диалог один."""
    performer_id: Mapped[UUID]
    job_id: Mapped[UUID | None]
    """jobs.jobs: FK в миграции."""
    response_id: Mapped[UUID | None] = mapped_column(unique=True)
    """jobs.responses: один диалог на отклик."""
    deal_id: Mapped[UUID | None] = mapped_column(index=True)
    """deals.deals: «Договорились» в чате или выбранный отклик диалога (6.3b)."""
    last_message_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint("client_id <> performer_id", name="two_parties"),
        CheckConstraint(
            "kind <> 'job_response' OR response_id IS NOT NULL", name="response_kind_refs"
        ),
        Index(
            "uq_conversations_direct_pair",
            "client_id",
            "performer_id",
            unique=True,
            postgresql_where=text("kind = 'direct'"),
        ),
    )


class ParticipantRow(Base):
    __tablename__ = "participants"

    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    """identity.users: FK в миграции."""
    role: Mapped[ParticipantRole] = mapped_column(str_enum(ParticipantRole, "role"))
    last_read_message_id: Mapped[UUID | None]
    muted_until: Mapped[datetime | None]

    __table_args__ = (Index("ix_participants_user_id", "user_id"),)


class MessageRow(UuidPkMixin, Base):
    __tablename__ = "messages"

    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id"))
    sender_id: Mapped[UUID | None]
    """identity.users: FK в миграции; None — системное сообщение."""
    client_msg_id: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[MessageKind] = mapped_column(str_enum(MessageKind, "kind"))
    body: Mapped[str | None] = mapped_column(Text)
    media_id: Mapped[UUID | None]
    """media.assets: FK в миграции (фото — v1)."""
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    source: Mapped[str] = mapped_column(String(16), server_default=text("'tma'"))
    moderation: Mapped[MessageModeration] = mapped_column(
        str_enum(MessageModeration, "moderation"), server_default=MessageModeration.OK.value
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    edited_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint(f"char_length(body) <= {MAX_BODY}", name="body_length"),
        UniqueConstraint("sender_id", "client_msg_id", name="uq_messages_sender_id_client_msg_id"),
        Index("ix_messages_conversation_id_id", "conversation_id", text("id DESC")),
        Index(
            "uq_messages_system_key",
            "conversation_id",
            "client_msg_id",
            unique=True,
            postgresql_where=text("sender_id IS NULL"),
        ),
    )


class ContactShareRow(UuidPkMixin, Base):
    """Сторона поделилась контактом по сделке (S54): по разу на вид контакта. Сам контакт — в
    сообщении `contact_share`."""

    __tablename__ = "contact_shares"

    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id"))
    deal_id: Mapped[UUID]
    """deals.deals: FK в миграции."""
    shared_by: Mapped[UUID]
    """identity.users: FK в миграции."""
    shared_with: Mapped[UUID]
    contact_type: Mapped[ContactType] = mapped_column(str_enum(ContactType, "contact_type"))
    message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "deal_id",
            "shared_by",
            "contact_type",
            name="uq_contact_shares_deal_id_shared_by_contact_type",
        ),
    )
