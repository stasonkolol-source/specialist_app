"""Блокировка между сторонами диалога (DEVELOPMENT_PLAN 4.7): пока она есть в любую сторону,
переписка — только для чтения. Хранится в identity и в диалог не пишется: разблокировали — диалог
снова открыт, без отдельного шага."""

from app.modules.identity.api import IdentityApi
from app.modules.messaging.domain.conversation import Conversation, ConversationStatus
from app.modules.messaging.errors import ConversationClosedError
from app.platform.kernel.ids import UserId


async def ensure_unblocked(
    identity: IdentityApi, conversation: Conversation, actor_id: UserId
) -> None:
    """Писать, договариваться и делиться контактом нельзя — 409 `conversation_closed` со
    статусом `blocked`, как у диалога, закрытого модерацией."""
    other = conversation.counterpart(actor_id).user_id
    if await identity.blocks_with(actor_id, [other]):
        raise ConversationClosedError(
            conversation_id=conversation.id,
            conversation_status=ConversationStatus.BLOCKED.value,
        )
