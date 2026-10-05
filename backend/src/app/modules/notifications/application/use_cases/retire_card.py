"""Погасить кнопки одной карточки B1 (задача `notifications.retire_card`, DEVELOPMENT_PLAN 5.7):
«Открыть заявку» остаётся, вместо отклика шаблоном, «Не подходит» и паузы — неактивная «Приём
откликов закрыт» (DisabledButton Bot API).

Сообщения уже нет или Telegram его не правит (400) и бот заблокирован (403) — ничего: кнопки
погаснуть не смогут, а нажатие и так ответит «заявка закрыта». 429 и слот лимитера дальше
горизонта — повтор задачи через `retry_after`, сеть и 5xx — повтор по стратегии.
"""

from dataclasses import dataclass

import structlog

from app.modules.identity.api import IdentityApi
from app.modules.notifications.application.ports import NotificationQuery, NotificationRenderer
from app.modules.notifications.domain.notification import DeliveryId, DeliveryStatus
from app.platform.telegram.port import (
    TelegramBlockedError,
    TelegramRejectedError,
    TelegramSender,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class RetireCardCommand:
    delivery_id: DeliveryId


class RetireCard:
    def __init__(
        self,
        query: NotificationQuery,
        identity: IdentityApi,
        renderer: NotificationRenderer,
        sender: TelegramSender,
    ) -> None:
        self._query, self._identity = query, identity
        self._renderer, self._sender = renderer, sender

    async def __call__(self, cmd: RetireCardCommand) -> bool:
        """Погасила ли кнопки."""
        target = await self._query.delivery(cmd.delivery_id)
        if (
            target is None
            or target.status is not DeliveryStatus.SENT
            or target.provider_message_id is None
            or not target.provider_message_id.isdigit()
        ):
            return False
        user = await self._identity.get_user(target.user_id)
        if user is None or user.is_deleted:
            return False
        buttons = self._renderer.retired_buttons(
            target.type, target.params, target.link, user.ui_locale
        )
        try:
            await self._sender.edit_buttons(
                target.chat_id, int(target.provider_message_id), buttons
            )
        except (TelegramBlockedError, TelegramRejectedError) as exc:
            log.info("card_not_retired", delivery_id=str(target.id), error=type(exc).__name__)
            return False
        return True
