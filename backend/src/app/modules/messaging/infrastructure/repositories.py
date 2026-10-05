"""Диалоги и сообщения (ADR-0020 §5): диалог с участниками — агрегат под блокировкой строки;
сообщение — простая запись, повтор `client_msg_id` того же автора отдаёт уже записанное.
Новые диалоги пары сериализует advisory lock транзакции. Обмен контактами — запись на сторону,
сделку и вид контакта (6.3b)."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.messaging.domain.conversation import (
    Conversation,
    ConversationKind,
    Participant,
    ParticipantRole,
)
from app.modules.messaging.domain.message import ContactType, Message, MessageModeration
from app.modules.messaging.errors import ConversationNotFoundError
from app.modules.messaging.infrastructure.models import (
    ContactShareRow,
    ConversationRow,
    MessageRow,
    ParticipantRow,
)
from app.platform.db.port import UnitOfWork
from app.platform.kernel.ids import UserId, new_id


class SqlConversationRepository:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def add(self, conversation: Conversation) -> None:
        self._uow.require_active()
        self._session.add(
            ConversationRow(
                id=conversation.id,
                kind=conversation.kind,
                status=conversation.status,
                client_id=conversation.client.user_id,
                performer_id=conversation.performer.user_id,
                job_id=conversation.job_id,
                response_id=conversation.response_id,
                deal_id=conversation.deal_id,
                last_message_at=conversation.last_message_at,
                created_at=conversation.created_at,
            )
        )
        await self._session.flush()
        self._session.add_all(
            ParticipantRow(
                conversation_id=conversation.id,
                user_id=participant.user_id,
                role=participant.role,
                last_read_message_id=participant.last_read_message_id,
            )
            for participant in (conversation.client, conversation.performer)
        )
        await self._session.flush()
        conversation.mark_persisted()
        self._uow.track(conversation)

    async def get_for_update(self, conversation_id: UUID) -> Conversation:
        self._uow.require_active()
        row = (
            await self._session.execute(
                select(ConversationRow)
                .where(ConversationRow.id == conversation_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            raise ConversationNotFoundError(conversation_id=conversation_id)
        participants = {
            p.role: p
            for p in (
                await self._session.execute(
                    select(ParticipantRow)
                    .where(ParticipantRow.conversation_id == conversation_id)
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        }
        conversation = Conversation(
            id=row.id,
            kind=row.kind,
            status=row.status,
            client=_participant(participants[ParticipantRole.CLIENT]),
            performer=_participant(participants[ParticipantRole.PERFORMER]),
            created_at=row.created_at,
            job_id=row.job_id,
            response_id=row.response_id,
            deal_id=row.deal_id,
            last_message_at=row.last_message_at,
        )
        self._uow.track(conversation)
        return conversation

    async def save(self, conversation: Conversation) -> None:
        self._uow.require_active()
        row = await self._session.get(ConversationRow, conversation.id)
        if row is None:
            raise ConversationNotFoundError(conversation_id=conversation.id)
        row.status = conversation.status
        row.deal_id = conversation.deal_id
        row.last_message_at = conversation.last_message_at
        for participant in (conversation.client, conversation.performer):
            await self._session.execute(
                update(ParticipantRow)
                .where(
                    ParticipantRow.conversation_id == conversation.id,
                    ParticipantRow.user_id == participant.user_id,
                )
                .values(last_read_message_id=participant.last_read_message_id)
                .execution_options(synchronize_session=False)
            )
        await self._session.flush()
        self._uow.track(conversation)

    async def lock_pair(self, client_id: UserId, performer_id: UserId) -> None:
        self._uow.require_active()
        key = func.hashtextextended(f"messaging.pair:{client_id}:{performer_id}", 0)
        await self._session.execute(select(func.pg_advisory_xact_lock(key)))

    async def of_response(self, response_id: UUID) -> UUID | None:
        stmt = select(ConversationRow.id).where(ConversationRow.response_id == response_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def direct_of(self, client_id: UserId, performer_id: UserId) -> UUID | None:
        stmt = select(ConversationRow.id).where(
            ConversationRow.kind == ConversationKind.DIRECT.value,
            ConversationRow.client_id == client_id,
            ConversationRow.performer_id == performer_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def of_deal(self, deal_id: UUID) -> UUID | None:
        stmt = select(ConversationRow.id).where(ConversationRow.deal_id == deal_id).limit(1)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def for_deal(self, deal_id: UUID, response_id: UUID | None) -> UUID | None:
        of_deal = ConversationRow.deal_id == deal_id
        match = (
            of_deal
            if response_id is None
            else or_(of_deal, ConversationRow.response_id == response_id)
        )
        # где договорились — первым; диалог отклика без сделки (deal_id NULL) — после
        stmt = (
            select(ConversationRow.id).where(match).order_by(of_deal.desc().nulls_last()).limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()


class SqlMessageStore:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def add(self, message: Message) -> Message:
        self._uow.require_active()
        stmt = (
            insert(MessageRow)
            .values(
                id=message.id,
                conversation_id=message.conversation_id,
                sender_id=message.sender_id,
                client_msg_id=message.client_msg_id,
                kind=message.kind,
                body=message.body,
                payload=message.payload,
                moderation=message.moderation,
                created_at=message.created_at,
            )
            .on_conflict_do_nothing(constraint="uq_messages_sender_id_client_msg_id")
            .returning(MessageRow.id)
        )
        inserted = (await self._session.execute(stmt)).scalar_one_or_none()
        if inserted is not None or message.sender_id is None or message.client_msg_id is None:
            return message
        sent = await self.by_client_id(message.sender_id, message.client_msg_id)
        return sent if sent is not None else message

    async def by_client_id(self, sender_id: UserId, client_msg_id: str) -> Message | None:
        row = (
            await self._session.execute(
                select(MessageRow).where(
                    MessageRow.sender_id == sender_id, MessageRow.client_msg_id == client_msg_id
                )
            )
        ).scalar_one_or_none()
        return _message(row) if row is not None else None

    async def system_exists(self, conversation_id: UUID, key: str) -> bool:
        stmt = select(MessageRow.id).where(
            MessageRow.conversation_id == conversation_id,
            MessageRow.sender_id.is_(None),
            MessageRow.client_msg_id == key,
        )
        return (await self._session.execute(stmt)).first() is not None

    async def get(self, message_id: UUID) -> Message | None:
        row = await self._session.get(MessageRow, message_id)
        return _message(row) if row is not None else None

    async def moderate(self, message_id: UUID, *, hidden: bool) -> bool:
        self._uow.require_active()
        result = await self._session.execute(
            update(MessageRow)
            .where(MessageRow.id == message_id, MessageRow.deleted_at.is_(None))
            .values(moderation=MessageModeration.HIDDEN if hidden else MessageModeration.OK)
            .execution_options(synchronize_session=False)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]  # CursorResult у DML

    async def forget(self, user_id: UserId, *, now: datetime) -> int:
        self._uow.require_active()
        result = await self._session.execute(
            update(MessageRow)
            .where(MessageRow.sender_id == user_id, MessageRow.deleted_at.is_(None))
            .values(body=None, payload={}, deleted_at=now)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult у DML


def _participant(row: ParticipantRow) -> Participant:
    return Participant(
        user_id=UserId(row.user_id),
        role=row.role,
        last_read_message_id=row.last_read_message_id,
    )


def _message(row: MessageRow) -> Message:
    return Message(
        id=row.id,
        conversation_id=row.conversation_id,
        sender_id=UserId(row.sender_id) if row.sender_id is not None else None,
        kind=row.kind,
        body=row.body,
        created_at=row.created_at,
        client_msg_id=row.client_msg_id,
        payload=dict(row.payload),
        moderation=row.moderation,
    )


class SqlContactShares:
    def __init__(self, session: AsyncSession, uow: UnitOfWork) -> None:
        self._session, self._uow = session, uow

    async def message_of(
        self, deal_id: UUID, shared_by: UserId, contact_type: ContactType
    ) -> UUID | None:
        stmt = select(ContactShareRow.message_id).where(
            ContactShareRow.deal_id == deal_id,
            ContactShareRow.shared_by == shared_by,
            ContactShareRow.contact_type == contact_type,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def add(
        self,
        *,
        conversation_id: UUID,
        deal_id: UUID,
        shared_by: UserId,
        shared_with: UserId,
        contact_type: ContactType,
        message_id: UUID,
    ) -> None:
        self._uow.require_active()
        self._session.add(
            ContactShareRow(
                id=new_id(),
                conversation_id=conversation_id,
                deal_id=deal_id,
                shared_by=shared_by,
                shared_with=shared_with,
                contact_type=contact_type,
                message_id=message_id,
            )
        )
        await self._session.flush()
