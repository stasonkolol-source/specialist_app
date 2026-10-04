"""Сроки хранения переписки (2.12b): выборка неактивных диалогов, физическое удаление и ссылки
диалогов на заявки (jobs.api.JobReferences: заявку удаляют только без переписки)."""

from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.api import JobReferences
from app.modules.messaging.infrastructure.models import (
    ContactShareRow,
    ConversationRow,
    MessageRow,
    ParticipantRow,
)
from app.platform.kernel.ids import MediaId, UserId


class SqlConversationRetention:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def inactive(self, before: datetime, *, after: UUID | None, limit: int) -> list[UUID]:
        last = func.coalesce(ConversationRow.last_message_at, ConversationRow.created_at)
        stmt = select(ConversationRow.id).where(last < before).order_by(ConversationRow.id)
        if after is not None:
            stmt = stmt.where(ConversationRow.id > after)
        return list((await self._session.scalars(stmt.limit(limit))).all())

    async def deals(self, conversation_ids: Collection[UUID]) -> dict[UUID, UUID]:
        if not conversation_ids:
            return {}
        rows = await self._session.execute(
            select(ConversationRow.id, ConversationRow.deal_id).where(
                ConversationRow.id.in_(conversation_ids), ConversationRow.deal_id.is_not(None)
            )
        )
        return {conversation_id: deal_id for conversation_id, deal_id in rows if deal_id}

    async def messages(self, conversation_ids: Collection[UUID]) -> dict[UUID, UUID]:
        if not conversation_ids:
            return {}
        rows = await self._session.execute(
            select(MessageRow.id, MessageRow.conversation_id).where(
                MessageRow.conversation_id.in_(conversation_ids)
            )
        )
        return dict(rows.all())

    async def attachments(self, conversation_ids: Collection[UUID]) -> list[tuple[UserId, MediaId]]:
        if not conversation_ids:
            return []
        rows = await self._session.execute(
            select(MessageRow.sender_id, MessageRow.media_id).where(
                MessageRow.conversation_id.in_(conversation_ids),
                MessageRow.media_id.is_not(None),
                MessageRow.sender_id.is_not(None),
            )
        )
        return [
            (UserId(sender_id), MediaId(media_id))
            for sender_id, media_id in rows
            if sender_id is not None and media_id is not None
        ]

    async def purge(self, conversation_ids: Collection[UUID]) -> None:
        if not conversation_ids:
            return
        ids = list(conversation_ids)
        for model in (ContactShareRow, MessageRow, ParticipantRow):
            await self._session.execute(delete(model).where(model.conversation_id.in_(ids)))
        await self._session.execute(delete(ConversationRow).where(ConversationRow.id.in_(ids)))


class SqlJobReferences(JobReferences):
    """Переписка по отклику держит FK на заявку и отклик (messaging_0001)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def referenced(self, ids: Collection[UUID]) -> frozenset[UUID]:
        wanted = set(ids)
        if not wanted:
            return frozenset()
        rows = await self._session.execute(
            select(ConversationRow.job_id, ConversationRow.response_id).where(
                or_(ConversationRow.job_id.in_(wanted), ConversationRow.response_id.in_(wanted))
            )
        )
        return frozenset(ref for row in rows for ref in row if ref in wanted)
