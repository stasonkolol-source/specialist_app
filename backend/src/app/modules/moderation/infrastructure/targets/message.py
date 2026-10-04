"""Адаптер цели «сообщение» (план 6.3a): фасад messaging для конвейера модерации.

Сообщение видно второй стороне сразу (переписка не ждёт проверки); флаг автопроверки (кейс в
очереди) или нарушение скрывает его, одобрение модератора — возвращает. Чистый итог автопроверки
ничего не меняет: опоздавший, он вернул бы сообщение, скрытое модератором по жалобе. Проверяется
текст участника; предложение из отклика уже проверено как отклик.
"""

from uuid import UUID

from app.modules.messaging.api import MessagingApi
from app.modules.moderation.application.ports import ModerationTarget, TargetContent
from app.platform.ai.port import ContentKind


class MessageTarget(ModerationTarget):
    def __init__(self, messaging: MessagingApi) -> None:
        self._messaging = messaging

    async def content(self, entity_id: UUID) -> TargetContent | None:
        message = await self._messaging.message_for_review(entity_id)
        if message is None:
            return None
        return TargetContent(
            author_id=message.sender_id, kind=ContentKind.MESSAGE, text=message.text, visible=True
        )

    async def publish(
        self,
        entity_id: UUID,
        *,
        version: int | None = None,  # noqa: ARG002 — у сообщения нет редакций
        auto: bool = False,
    ) -> None:
        if auto:  # сообщение и так видно; скрытое модератором, пока шла проверка, — его решение
            return
        await self._messaging.approve_message(entity_id)

    async def hide(
        self,
        entity_id: UUID,
        *,
        reason_code: str,  # noqa: ARG002 — причина остаётся в кейсе модерации
    ) -> None:
        await self._messaging.hide_message(entity_id)
