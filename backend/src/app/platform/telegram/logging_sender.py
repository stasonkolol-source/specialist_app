"""Отправитель Telegram до адаптера на aiogram (шаг 2.3b): сообщения не уходят."""

import structlog

from app.platform.telegram.port import OutgoingMessage, SentMessage

log = structlog.get_logger(__name__)


class LoggingTelegramSender:
    """Сообщение не уходит; в лог — только факт отправки (адрес и текст — нет: это
    персональные данные)."""

    async def send(self, message: OutgoingMessage) -> SentMessage:
        log.info("telegram_send_skipped", length=len(message.text), buttons=len(message.buttons))
        return SentMessage(message_id=0)
