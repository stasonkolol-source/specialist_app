"""Отправитель Telegram для тестов (ADR-0020 §11): запоминает сообщения, может падать."""

from dataclasses import dataclass, field

from app.platform.kernel.errors import ExternalServiceError
from app.platform.telegram.port import OutgoingMessage, SentMessage, ShareCard


@dataclass
class RecordingTelegramSender:
    sent: list[OutgoingMessage] = field(default_factory=list)
    failing: bool = False
    """Bot API недоступен: send бросает ExternalServiceError."""
    error: Exception | None = None
    """Ответ Bot API ошибкой порта: 429, 403, 400 (port.py)."""

    async def send(self, message: OutgoingMessage) -> SentMessage:
        if self.error is not None:
            raise self.error
        if self.failing:
            raise ExternalServiceError(service="telegram")
        self.sent.append(message)
        return SentMessage(message_id=1000 + len(self.sent))


@dataclass
class RecordingPreparedMessages:
    """Карточки шаринга (7.4): запоминает, что готовили; `failing` — Bot API не принял."""

    prepared: list[tuple[int, ShareCard]] = field(default_factory=list)
    failing: bool = False

    async def prepare(self, telegram_user_id: int, card: ShareCard) -> str | None:
        if self.failing:
            return None
        self.prepared.append((telegram_user_id, card))
        return f"prepared-{len(self.prepared)}"
