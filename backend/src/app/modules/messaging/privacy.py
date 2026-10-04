"""Сроки хранения и выгрузка данных messaging (ARCHITECTURE §7.10, DEVELOPMENT_PLAN 2.12b).

Правило: диалог — 12 месяцев после последнего сообщения. Выгрузка: диалоги пользователя, его
участие и его собственные сообщения, обмены контактами с его участием. Сообщения собеседника —
его данные: в выгрузку не идут.
"""

from uuid import UUID

from sqlalchemy import Select, or_, select

from app.modules.messaging.application.use_cases.purge_inactive_conversations import (
    PurgeInactiveConversations,
    PurgeInactiveConversationsCommand,
)
from app.modules.messaging.infrastructure.models import (
    ContactShareRow,
    ConversationRow,
    MessageRow,
    ParticipantRow,
)
from app.platform.privacy.registry import ExportTable, RetentionRun, export_section, retention_rule


@retention_rule("messaging.conversations", keep="12 мес. после последнего сообщения")
async def conversations(run: RetentionRun) -> int:
    async with run.container() as request:
        purge = await request.get(PurgeInactiveConversations)
        return await purge(PurgeInactiveConversationsCommand(now=run.now))


def _conversations(user_id: UUID) -> Select[UUID]:
    return select(ParticipantRow.conversation_id).where(ParticipantRow.user_id == user_id)


export_section(
    "messaging",
    ExportTable(ConversationRow, lambda user: ConversationRow.id.in_(_conversations(user))),
    ExportTable(ParticipantRow, lambda user: ParticipantRow.user_id == user),
    ExportTable(MessageRow, lambda user: MessageRow.sender_id == user),
    ExportTable(
        ContactShareRow,
        lambda user: or_(ContactShareRow.shared_by == user, ContactShareRow.shared_with == user),
    ),
)
