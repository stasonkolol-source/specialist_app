"""Срок хранения переписки (правило `messaging.conversations` ночной `platform.retention_sweep`;
ARCHITECTURE §7.10, ADR-0010, DEVELOPMENT_PLAN 2.12b).

Диалог, где 12 месяцев не было сообщений (закрытый или заброшенный), удаляется целиком:
участники, сообщения с файлами, записи об обмене контактами. Не удаляется, пока о его
сообщении открыт кейс модерации или по его сделке идёт спор (legal hold, RetentionHold):
удержанные проверяются снова следующей ночью. Страница — одна транзакция.

До 2.12b текст сообщений стирался по одному через 12 месяцев (`messaging.purge_messages`, 6.3a);
матрица считает срок от последнего сообщения диалога — так живая переписка не теряет начало.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from app.modules.media.api import MediaApi
from app.modules.messaging.application.ports import ConversationRetention
from app.platform.db.port import UnitOfWork
from app.platform.privacy.port import HoldKind, RetentionHold

KEEP: Final = timedelta(days=365)
"""12 месяцев после последнего сообщения (§7.10)."""
BATCH: Final = 200


@dataclass(frozen=True, slots=True, kw_only=True)
class PurgeInactiveConversationsCommand:
    now: datetime
    limit: int = BATCH


class PurgeInactiveConversations:
    def __init__(
        self,
        uow: UnitOfWork,
        retention: ConversationRetention,
        hold: RetentionHold,
        media: MediaApi,
    ) -> None:
        self._uow, self._retention, self._hold, self._media = uow, retention, hold, media

    async def __call__(self, cmd: PurgeInactiveConversationsCommand) -> int:
        """Сколько диалогов удалено."""
        purged = 0
        cursor: UUID | None = None
        while True:
            async with self._uow:
                page = await self._retention.inactive(cmd.now - KEEP, after=cursor, limit=cmd.limit)
                free = await self._free(page)
                for owner_id, media_id in await self._retention.attachments(free):
                    await self._media.discard(owner_id, media_id)
                await self._retention.purge(free)
            purged += len(free)
            if len(page) < cmd.limit:
                return purged
            cursor = page[-1]

    async def _free(self, conversation_ids: list[UUID]) -> list[UUID]:
        if not conversation_ids:
            return []
        deals = await self._retention.deals(conversation_ids)
        disputed = await self._hold.held(HoldKind.DEAL, list(deals.values()))
        held = {conversation for conversation, deal in deals.items() if deal in disputed}
        messages = await self._retention.messages(conversation_ids)
        reported = await self._hold.held(HoldKind.MESSAGE, list(messages))
        held |= {messages[message_id] for message_id in reported}
        return [c for c in conversation_ids if c not in held]
